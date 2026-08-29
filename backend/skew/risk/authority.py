"""The earned risk authority.

    Tier  Max loss per trade  Promotion condition               Demotion
    ────  ──────────────────  ────────────────────────────────  ───────────────────────
    0     0.5% of equity      default                           —
    1     1.0%                3 closed trades, no gate breach   any breach
    2     2.0%                6 closed trades, drawdown < 3%    breach, or drawdown > 3%

The narrative here is the point, and no competitor has it: **an agent that earns
the right to size up.** It starts at half a percent of equity per trade and has
to demonstrate a clean record before it is allowed more. One breach and it goes
back to the beginning.

This is what a brokerage actually wants from autonomous agents on its API — not
a system that promises to be careful, but one whose authority is mechanically
tied to its record, and whose record lives in an append-only log anyone can read.

State persists in SQLite so the tier survives a restart. A tier that reset on
every deploy would not be earned; it would be decorative.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from skew.audit.models import EquityRow, PositionRow, RiskStateRow
from skew.config import settings
from skew.db import session_scope
from skew.models import RiskAuthority

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tier:
    level: int
    # Per-trade: what any single position may risk.
    max_loss_pct: float
    # Portfolio: what all open positions may risk together. A separate number —
    # merging the two locked the desk out after its first fill.
    portfolio_pct: float
    trades_required: int
    max_drawdown_pct: float
    description: str


TIERS: dict[int, Tier] = {
    0: Tier(0, 0.005, 0.015, 0, 100.0, "starting authority — 0.5% per trade, 1.5% deployed"),
    1: Tier(1, 0.010, 0.030, 3, 100.0, "3 closed trades with no gate breach"),
    2: Tier(2, 0.020, 0.050, 6, 3.0, "6 closed trades and drawdown under 3%"),
}
MAX_TIER = max(TIERS)

# Drawdown above this demotes, at any tier.
DEMOTION_DRAWDOWN_PCT = 3.0


def _state_row(session) -> RiskStateRow:
    row = session.get(RiskStateRow, 1)
    if row is None:
        row = RiskStateRow(id=1, tier=settings.risk_tier_start, closed_trades=0, breaches=0)
        session.add(row)
        session.flush()
    return row


def record_equity(equity: float) -> None:
    """Sample account equity. Feeds the drawdown term."""
    if equity <= 0:
        log.warning("Refusing to record non-positive equity %r", equity)
        return
    with session_scope() as session:
        session.add(EquityRow(ts=datetime.now(UTC), equity=float(equity)))
        row = _state_row(session)
        if equity > row.peak_equity:
            row.peak_equity = float(equity)


def current_drawdown(equity: float) -> float:
    """Percentage below the high-water mark. Never negative."""
    with session_scope() as session:
        peak = float(_state_row(session).peak_equity or 0.0)
    peak = max(peak, equity)
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - equity) / peak * 100.0)


def record_breach(reason: str) -> int:
    """A gate breach on a live position. Demotes immediately.

    Demotion is to tier 0, not one step down. The authority was granted on a
    clean record; a breach ends that record.
    """
    with session_scope() as session:
        row = _state_row(session)
        row.breaches += 1
        previous = row.tier
        row.tier = 0
        row.note = f"demoted from tier {previous} after breach: {reason}"[:500]
        row.updated_at = datetime.now(UTC)
        log.warning("RISK BREACH — demoted tier %s -> 0: %s", previous, reason)
        return row.tier


def record_closed_trade(clean: bool = True) -> int:
    """Log a closed position and re-evaluate the tier."""
    with session_scope() as session:
        row = _state_row(session)
        row.closed_trades += 1
        if not clean:
            row.breaches += 1
            row.tier = 0
            row.note = "demoted after a position closed on a breach"
        row.updated_at = datetime.now(UTC)
        return row.tier


def evaluate_tier(equity: float) -> int:
    """Recompute the tier from the record. Idempotent; safe to call every cycle.

    Promotion requires the trade count *and* a clean breach record. Any breach
    at all pins the desk to tier 0 — the counter is not forgiven with time,
    because "wait long enough and it does not count" is not a risk policy.
    """
    drawdown = current_drawdown(equity)

    with session_scope() as session:
        row = _state_row(session)
        closed, breaches = row.closed_trades, row.breaches
        previous = row.tier

        if breaches > 0:
            earned = 0
        elif drawdown > DEMOTION_DRAWDOWN_PCT:
            # Too far below the high-water mark for the top tier, whatever the
            # trade count says.
            earned = min(1, _by_trade_count(closed))
        else:
            earned = _by_trade_count(closed)

        if earned != previous:
            row.tier = earned
            row.updated_at = datetime.now(UTC)
            direction = "promoted" if earned > previous else "demoted"
            row.note = (
                f"{direction} {previous} -> {earned}: {closed} closed trades, "
                f"{breaches} breaches, drawdown {drawdown:.2f}%"
            )
            log.info("risk tier %s: %s", direction, row.note)
        return row.tier


def _by_trade_count(closed: int) -> int:
    earned = 0
    for level in sorted(TIERS):
        if closed >= TIERS[level].trades_required:
            earned = level
    return earned


def _next_promotion_copy(tier: int, closed: int, breaches: int, drawdown: float) -> str:
    """Human copy for the UI: what it would take to size up."""
    if breaches > 0:
        return (
            f"Pinned to tier 0 by {breaches} recorded breach"
            f"{'es' if breaches != 1 else ''}. Authority is not restored by time."
        )
    if tier >= MAX_TIER:
        return f"Top tier. {closed} closed trades, no breaches, drawdown {drawdown:.1f}%."

    nxt = TIERS[tier + 1]
    needed = max(0, nxt.trades_required - closed)
    parts = []
    if needed:
        parts.append(f"{needed} more clean closed trade{'s' if needed != 1 else ''}")
    if drawdown > nxt.max_drawdown_pct:
        parts.append(f"drawdown back under {nxt.max_drawdown_pct:.0f}% (currently {drawdown:.1f}%)")
    if not parts:
        parts.append("conditions met — promotes on the next evaluation")
    return (
        f"Tier {nxt.level} ({nxt.max_loss_pct:.1%} per trade, {nxt.portfolio_pct:.1%} "
        f"deployed) needs " + " and ".join(parts) + "."
    )


def get_authority(
    equity: float,
    used_dollars: float = 0.0,
    open_positions: int = 0,
) -> RiskAuthority:
    """The full risk picture, as the API and the gates see it."""
    tier_level = evaluate_tier(equity)
    tier = TIERS[tier_level]
    drawdown = current_drawdown(equity)

    with session_scope() as session:
        row = _state_row(session)
        closed, breaches = row.closed_trades, row.breaches

    return RiskAuthority(
        tier=tier_level,
        max_loss_pct=tier.max_loss_pct,
        budget_dollars=round(equity * tier.max_loss_pct, 2),
        portfolio_pct=tier.portfolio_pct,
        portfolio_cap_dollars=round(equity * tier.portfolio_pct, 2),
        used_dollars=round(used_dollars, 2),
        closed_trades=closed,
        breaches=breaches,
        drawdown_pct=round(drawdown, 4),
        equity=round(equity, 2),
        open_positions=open_positions,
        max_concurrent_positions=settings.max_concurrent_positions,
        next_promotion=_next_promotion_copy(tier_level, closed, breaches, drawdown),
    )


def committed_dollars() -> tuple[float, int]:
    """Max loss already committed to open positions, and how many there are."""
    with session_scope() as session:
        rows = session.scalars(select(PositionRow).where(PositionRow.is_open.is_(True))).all()
    return round(sum(float(r.max_loss or 0.0) for r in rows), 2), len(rows)


def reset_state() -> None:
    """Wipe the tier state. Test and demo-reset helper; never called by the loop."""
    with session_scope() as session:
        row = _state_row(session)
        row.tier = settings.risk_tier_start
        row.closed_trades = 0
        row.breaches = 0
        row.peak_equity = 0.0
        row.note = "reset"
        row.updated_at = datetime.now(UTC)
