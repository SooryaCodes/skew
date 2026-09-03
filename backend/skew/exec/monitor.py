"""Position monitoring and exit rules.

Three reasons to close, plus the assignment defence, checked in this order:

1. **Profit target.** Half the credit captured. Holding a credit spread to
   expiry for the last few dollars means carrying gamma risk into the final week
   for a shrinking reward — the classic way to give back a month of profits.
2. **Loss limit.** Down a multiple of the credit received. The structure is
   defined-risk, so this is not about solvency; it is about not sitting in a
   position whose premise has been falsified.
3. **DTE threshold.** Close before the last week. Gamma rises sharply near
   expiry and a short spread that has been quiet for a month can move through
   its whole width in a day. This is the calendar rule — there is no
   date-driven flatten; the desk trades until its rules say otherwise.

The kill switch halts *entries*, never monitoring. A system that stops watching
its open positions when you pull the handbrake is worse than one with no
handbrake at all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select

from skew.audit.models import PositionRow
from skew.config import Settings
from skew.config import settings as default_settings
from skew.db import session_scope
from skew.models import CONTRACT_MULTIPLIER, Position, Structure

log = logging.getLogger(__name__)


@dataclass
class ExitSignal:
    """Whether to close, and the sentence explaining why."""

    should_exit: bool
    rule: str = ""
    reason: str = ""

    def __bool__(self) -> bool:
        return self.should_exit


NO_EXIT = ExitSignal(False)


def current_value(structure: Structure, mids: dict[str, float]) -> float:
    """Signed liquidation value from live mids. Negative for an open credit spread."""
    return sum(
        leg.signed_ratio * mids.get(leg.symbol, leg.mid) * CONTRACT_MULTIPLIER * structure.qty
        for leg in structure.legs
    )


def unrealised_pnl(structure: Structure, mids: dict[str, float]) -> float:
    """Mark-to-market P&L against the entry price."""
    entry = sum(
        leg.signed_ratio * leg.mid * CONTRACT_MULTIPLIER * structure.qty for leg in structure.legs
    )
    return current_value(structure, mids) - entry


def evaluate_exit(
    structure: Structure,
    mids: dict[str, float],
    as_of: date | None = None,
    settings: Settings | None = None,
    spot: float | None = None,
) -> ExitSignal:
    """Decide whether an open structure should be closed now."""
    cfg = settings or default_settings
    today = as_of or datetime.now(UTC).date()
    expiry = min(leg.expiry for leg in structure.legs)
    dte = (expiry - today).days
    pnl = unrealised_pnl(structure, mids)

    # 0 — assignment defence. A short leg trading in the money can be assigned
    # at ANY time, leaving the account holding stock the agent never intended —
    # unacceptable while judges watch an unattended desk. Close the whole
    # structure the moment a short leg crosses.
    if spot is not None and spot > 0:
        for leg in structure.legs:
            if leg.side != "SELL":
                continue
            itm = (leg.right == "PUT" and spot < leg.strike) or (
                leg.right == "CALL" and spot > leg.strike
            )
            if itm:
                return ExitSignal(
                    True,
                    "short_itm",
                    f"Defensive exit — the short {leg.right.lower()} at {leg.strike:g} is in "
                    f"the money with spot at {spot:.2f}. Assignment risk is not a risk this "
                    f"desk carries; closing the whole structure early.",
                )

    # 1 — profit target.
    if structure.is_credit and structure.net_credit > 0:
        captured = pnl / structure.net_credit
        if captured >= cfg.profit_target_pct:
            return ExitSignal(
                True,
                "profit_target",
                f"Captured {captured:.0%} of the ${structure.net_credit:,.2f} credit "
                f"(+${pnl:,.2f}). Target is {cfg.profit_target_pct:.0%} — taking it rather "
                f"than carrying gamma into the last week for the remainder.",
            )
    elif not structure.is_credit and structure.max_profit > 0:
        captured = pnl / structure.max_profit
        if captured >= cfg.profit_target_pct:
            return ExitSignal(
                True,
                "profit_target",
                f"Captured {captured:.0%} of the ${structure.max_profit:,.2f} maximum "
                f"(+${pnl:,.2f}), at or above the {cfg.profit_target_pct:.0%} target.",
            )

    # 2 — loss limit.
    reference = abs(structure.net_credit) if structure.net_credit else structure.max_loss
    limit = reference * cfg.loss_limit_multiple
    if pnl < 0 and abs(pnl) >= limit and limit > 0:
        return ExitSignal(
            True,
            "loss_limit",
            f"Down ${abs(pnl):,.2f}, at or beyond {cfg.loss_limit_multiple:g}x the "
            f"${reference:,.2f} opening premium. The premise has been falsified; closing "
            f"rather than hoping.",
        )

    # 3 — days to expiry.
    if dte <= cfg.exit_dte_threshold:
        return ExitSignal(
            True,
            "dte",
            f"{dte} days to expiry, at or under the {cfg.exit_dte_threshold}-day threshold. "
            f"Gamma rises sharply into expiry and a quiet spread can travel its whole width "
            f"in a day.",
        )

    return NO_EXIT


# ------------------------------------------------------------------ persistence


def open_positions() -> list[PositionRow]:
    with session_scope() as session:
        return list(session.scalars(select(PositionRow).where(PositionRow.is_open.is_(True))).all())


def record_open(structure: Structure, order_id: str) -> None:
    """Record a filled structure as one position, not as N legs.

    Alpaca reports positions leg by leg; the desk thinks in structures, and the
    exit rules only make sense at that level.
    """
    with session_scope() as session:
        if session.get(PositionRow, structure.id) is not None:
            log.warning("position %s already open; not duplicating", structure.id)
            return
        session.add(
            PositionRow(
                id=structure.id,
                account=_connected_account(),
                symbol=structure.symbol,
                kind=structure.kind,
                opened_at=datetime.now(UTC),
                expiry=min(leg.expiry for leg in structure.legs),
                qty=structure.qty,
                entry_credit=structure.net_credit,
                max_loss=structure.max_loss,
                is_open=True,
                legs=[leg.symbol for leg in structure.legs],
                structure=structure.model_dump(mode="json"),
            )
        )


def record_close(structure_id: str, realized_pnl: float, reason: str) -> None:
    with session_scope() as session:
        row = session.get(PositionRow, structure_id)
        if row is None:
            log.warning("cannot close unknown position %s", structure_id)
            return
        row.is_open = False
        row.closed_at = datetime.now(UTC)
        row.realized_pnl = float(realized_pnl)
        row.exit_reason = reason


def to_position(row: PositionRow, mids: dict[str, float] | None = None) -> Position:
    """Serialise a stored position for the API, marked to market when mids exist."""
    structure = Structure.model_validate(row.structure) if row.structure else None
    pnl = 0.0
    value = 0.0
    if structure and mids:
        value = current_value(structure, mids)
        pnl = unrealised_pnl(structure, mids)

    opened = row.opened_at
    if opened is not None and opened.tzinfo is None:
        opened = opened.replace(tzinfo=UTC)

    dte = (row.expiry - datetime.now(UTC).date()).days if row.expiry else 0
    return Position(
        id=row.id,
        symbol=row.symbol,
        kind=row.kind,
        legs=list(row.legs or []),
        qty=row.qty,
        opened_at=opened,
        entry_credit=row.entry_credit,
        current_value=round(value, 2),
        unrealized_pnl=round(pnl, 2),
        max_loss=row.max_loss,
        dte=dte,
        exit_reason=row.exit_reason,
    )


def fetch_mids(broker: Any, symbols: list[str]) -> dict[str, float]:
    """Current mid per option contract, for marking positions to market."""
    if not symbols:
        return {}
    from alpaca.data.requests import OptionLatestQuoteRequest

    try:
        quotes = broker.option_data.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=symbols)
        )
    except Exception as exc:  # noqa: BLE001 — a stale mark must not stop monitoring
        log.warning("could not fetch option quotes for marking: %s", exc)
        return {}

    out: dict[str, float] = {}
    for symbol, quote in (quotes or {}).items():
        bid = float(getattr(quote, "bid_price", 0.0) or 0.0)
        ask = float(getattr(quote, "ask_price", 0.0) or 0.0)
        if bid > 0 and ask > 0:
            out[symbol] = (bid + ask) / 2.0
    return out


def _connected_account() -> str:
    from skew.audit.log import connected_account

    return connected_account()


def monitor_positions(broker: Any, settings: Settings | None = None) -> list[dict[str, Any]]:
    """Mark every open position and return those that should be closed.

    Runs regardless of the kill switch: halting entries is not the same as
    looking away from what is already open.
    """
    cfg = settings or default_settings
    rows = open_positions()
    if not rows:
        return []

    contracts = sorted({sym for row in rows for sym in (row.legs or [])})
    mids = fetch_mids(broker, contracts)

    # Spot per underlying, for the assignment-defence rule. A failed spot fetch
    # must not stop the DTE/deadline rules from running — degrade to None.
    spots: dict[str, float] = {}
    for symbol in sorted({row.symbol for row in rows}):
        try:
            spots[symbol] = float(broker.fetch_spot(symbol))
        except Exception:  # noqa: BLE001 — monitoring continues without spot
            log.warning("spot unavailable for %s — assignment check skipped this pass", symbol)

    actions: list[dict[str, Any]] = []
    for row in rows:
        if not row.structure:
            continue
        structure = Structure.model_validate(row.structure)
        signal = evaluate_exit(structure, mids, settings=cfg, spot=spots.get(row.symbol))
        pnl = unrealised_pnl(structure, mids)
        if signal.should_exit:
            actions.append(
                {
                    "structure_id": row.id,
                    "symbol": row.symbol,
                    "structure": structure,
                    "rule": signal.rule,
                    "reason": signal.reason,
                    "unrealized_pnl": round(pnl, 2),
                    "mids": mids,
                }
            )
    return actions
