"""Atomic multi-leg order submission.

Two rules from docs/01-ARCHITECTURE.md §7 that will bite if forgotten, both
enforced here rather than trusted to a caller:

* **Never leg in.** A spread goes as one ``mleg`` order or it does not go. Legging
  in means a window where the short leg is filled and the long one is not, which
  is a naked short option — the thing this desk exists never to have.
* **Sign convention.** For an mleg limit order, a **positive limit price is a
  debit and a negative one is a credit.** Inverting it inverts the trade. It is
  derived in exactly one place — ``Structure.limit_price`` — and asserted here.

And one from docs/05-SECURITY.md: **re-run the gate chain immediately before
submission.** Market data moved while the model was thinking, and a candidate
built ninety seconds ago may no longer be one.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from skew.config import Settings
from skew.config import settings as default_settings
from skew.gates.base import GateContext, run_gates
from skew.models import CONTRACT_MULTIPLIER, Candidate, Structure

log = logging.getLogger(__name__)


class SubmissionRefused(RuntimeError):
    """Refused before anything reached the broker. Carries a human-readable reason."""


class PreflightFailed(SubmissionRefused):
    """The gate chain no longer passes. The market moved while we were deciding."""


def client_order_id(structure: Structure, when: datetime | None = None) -> str:
    """A deterministic, idempotent client order id for OPENING orders.

    Same structure, same day -> same id, so Alpaca itself rejects a duplicate
    submission. The old scheme embedded the minute, which was not idempotency:
    two cycles five minutes apart submitted the same AMD spread twice and both
    filled. Closing orders use closing_order_id below — a close may
    legitimately be retried after an unfilled attempt.
    """
    import hashlib

    day = (when or datetime.now(UTC)).strftime("%y%m%d")
    digest = hashlib.sha256(f"{structure.id}|{structure.qty}|{day}".encode()).hexdigest()[:10]
    kind = structure.kind.replace("_", "")[:8]
    return f"skew-{structure.symbol}-{kind}-{day}-{digest}"[:64]


def closing_order_id(structure: Structure, when: datetime | None = None) -> str:
    """Client id for a CLOSING order — timestamped, because a close that
    expired unfilled must be retriable with a fresh id."""
    stamp = (when or datetime.now(UTC)).strftime("%y%m%d%H%M")
    tail = uuid.uuid4().hex[:6]
    return f"skewX-{structure.symbol}-{stamp}-{tail}"[:64]




RESTING_OR_FILLED = {"new", "accepted", "pending_new", "partially_filled", "held", "filled"}


def _duplicate_of(structure: Structure) -> str | None:
    """A reason string when this structure is already open or already has a
    live opening order; None when it is genuinely new. Checked BEFORE the
    order goes out — the client-order-id is the backstop, not the guard."""
    from skew.audit.models import OrderRow, PositionRow
    from skew.db import session_scope

    from sqlalchemy import select

    with session_scope() as session:
        row = session.get(PositionRow, structure.id)
        if row is not None and row.is_open:
            return f"position {structure.id} is already open"
        orders = session.scalars(
            select(OrderRow).where(
                OrderRow.structure_id == structure.id, OrderRow.intent == "OPEN"
            )
        ).all()
        for order in orders:
            if (order.status or "").lower() in RESTING_OR_FILLED:
                return (
                    f"opening order {order.client_order_id} for {structure.id} is "
                    f"already {order.status} at the broker"
                )
    return None


def build_mleg_request(
    structure: Structure,
    client_id: str,
    use_limit: bool = True,
    settings: Settings | None = None,
) -> Any:
    """Construct the Alpaca order request for one structure.

    Between 2 and 4 legs, ``position_intent`` on every leg, ratio quantities
    already normalised to a GCD of 1 by ``structures.base.assemble``.
    """
    from alpaca.trading.enums import OrderClass, OrderSide, PositionIntent, TimeInForce
    from alpaca.trading.requests import (
        LimitOrderRequest,
        MarketOrderRequest,
        OptionLegRequest,
    )

    cfg = settings or default_settings
    from skew.config import assert_paper_only

    assert_paper_only(cfg.alpaca_base_url)

    if not 2 <= len(structure.legs) <= 4:
        raise SubmissionRefused(
            f"Alpaca permits 2–4 legs for an options mleg order; this structure has "
            f"{len(structure.legs)}."
        )

    side_map = {"BUY": OrderSide.BUY, "SELL": OrderSide.SELL}
    intent_map = {
        "BTO": PositionIntent.BUY_TO_OPEN,
        "STO": PositionIntent.SELL_TO_OPEN,
        "BTC": PositionIntent.BUY_TO_CLOSE,
        "STC": PositionIntent.SELL_TO_CLOSE,
    }

    legs = [
        OptionLegRequest(
            symbol=leg.symbol,
            side=side_map[leg.side],
            position_intent=intent_map[leg.position_intent],
            ratio_qty=leg.ratio_qty,
        )
        for leg in structure.legs
    ]

    common = {
        "qty": structure.qty,
        "order_class": OrderClass.MLEG,
        "time_in_force": TimeInForce.DAY,
        "legs": legs,
        "client_order_id": client_id,
    }

    if not use_limit:
        return MarketOrderRequest(**common)

    limit_price = structure.limit_price
    # The assertion that keeps the sign convention honest. A credit structure
    # must submit a negative limit and a debit a positive one; the reverse would
    # be a completely different trade that would still fill.
    if structure.is_credit and limit_price >= 0:
        raise SubmissionRefused(
            f"Credit structure {structure.id} produced a non-negative limit price "
            f"{limit_price:+.2f}. Alpaca reads positive as a debit — refusing to invert the trade."
        )
    if not structure.is_credit and limit_price <= 0:
        raise SubmissionRefused(
            f"Debit structure {structure.id} produced a non-positive limit price "
            f"{limit_price:+.2f}. Refusing to invert the trade."
        )

    # UNITS: structure.limit_price is the position's DOLLAR total (mid x 100
    # x qty); Alpaca's mleg limit_price is PER SHARE for one unit of the
    # spread. Sending dollars made every credit order demand its whole credit
    # per share (never filled — five orders expired that way) and every debit
    # order into an unbounded marketable buy (AMD filled $1.00/share worse
    # than intended). This division is the entire unit boundary; the model
    # keeps its dollar convention everywhere else.
    per_share = limit_price / (CONTRACT_MULTIPLIER * max(structure.qty, 1))

    return LimitOrderRequest(**common, limit_price=round(per_share, 2))


def preflight(
    candidate: Candidate,
    context: GateContext,
) -> Candidate:
    """Re-run the full gate chain immediately before submission.

    Market data moves between candidate construction and order placement — the
    model spends a second or two thinking, and a five-minute-old quote is a
    different market. A candidate that no longer passes is refused here, and the
    refusal is logged like any other.
    """
    rechecked = run_gates(candidate, context)
    if not rechecked.passed_all:
        failed = ", ".join(g.gate for g in rechecked.failed_gates)
        raise PreflightFailed(
            f"Pre-flight recheck failed on {failed}. The market moved between candidate "
            f"construction and submission: "
            f"{'; '.join(g.reason for g in rechecked.failed_gates)}"
        )
    return rechecked


def submit_structure(
    broker: Any,
    candidate: Candidate,
    context: GateContext,
    use_limit: bool = True,
    settings: Settings | None = None,
    skip_preflight: bool = False,
) -> dict[str, Any]:
    """Submit one structure as a single atomic multi-leg order.

    Returns a record of what was sent and what came back. Raises
    :class:`SubmissionRefused` — never submits a partial position, and never
    falls back to legging in.
    """
    cfg = settings or default_settings
    structure = candidate.structure

    if cfg.kill_switch:
        raise SubmissionRefused("Kill switch is engaged. No new positions.")

    duplicate = _duplicate_of(structure)
    if duplicate:
        raise SubmissionRefused(
            f"Duplicate refused — {duplicate}. One structure, one position: the "
            f"desk never doubles into legs it already holds or has resting."
        )

    if not skip_preflight:
        preflight(candidate, context)

    client_id = client_order_id(structure)
    request = build_mleg_request(structure, client_id, use_limit=use_limit, settings=cfg)

    log.info(
        "submitting %s as one mleg order: %d legs, limit %+.2f (%s), client_order_id %s",
        structure.id,
        len(structure.legs),
        structure.limit_price,
        "credit" if structure.is_credit else "debit",
        client_id,
    )

    order = broker.submit_order(request)

    record = {
        "client_order_id": client_id,
        "broker_order_id": str(getattr(order, "id", "") or ""),
        "status": str(getattr(order, "status", "") or "submitted"),
        "symbol": structure.symbol,
        "structure_id": structure.id,
        "kind": structure.kind,
        "qty": structure.qty,
        "limit_price": structure.limit_price,
        "net_credit": structure.net_credit,
        "max_loss": structure.max_loss,
        "legs": [
            {
                "symbol": leg.symbol,
                "side": leg.side,
                "position_intent": leg.position_intent,
                "ratio_qty": leg.ratio_qty,
            }
            for leg in structure.legs
        ],
        "submitted_at": datetime.now(UTC).isoformat(),
        # The full structure rides along so reconciliation can promote a
        # late fill into a position without guessing at the legs.
        "structure": structure.model_dump(mode="json"),
    }
    _persist_order(record)
    return record


def _persist_order(record: dict[str, Any], intent: str = "OPEN") -> None:
    from skew.audit.models import OrderRow
    from skew.db import session_scope

    with session_scope() as session:
        existing = session.get(OrderRow, record["client_order_id"])
        if existing is not None:
            # Idempotency: the same client_order_id must never create a second
            # row, so a retry after a network timeout stays a single order.
            log.warning("order %s already recorded; not duplicating", record["client_order_id"])
            return
        session.add(
            OrderRow(
                client_order_id=record["client_order_id"],
                broker_order_id=record.get("broker_order_id"),
                symbol=record["symbol"],
                structure_id=record["structure_id"],
                kind=record["kind"],
                intent=intent,
                qty=record["qty"],
                limit_price=record["limit_price"],
                net_credit=record["net_credit"],
                max_loss=record["max_loss"],
                status=record["status"],
                legs=record["legs"],
                detail={
                    "submitted_at": record["submitted_at"],
                    "structure": record.get("structure"),
                },
            )
        )


def already_submitted(client_id: str) -> bool:
    from skew.audit.models import OrderRow
    from skew.db import session_scope

    with session_scope() as session:
        return session.get(OrderRow, client_id) is not None
