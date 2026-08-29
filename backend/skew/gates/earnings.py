"""Earnings gate.

Blocks new entries inside the earnings window. The reason is specific to what
this desk does: implied volatility is elevated before a report *because* a known
event is coming, and it collapses the moment the number is out. That collapse —
IV crush — is not the variance risk premium. It is the market correctly pricing
a binary event, and collecting it is a bet on the outcome of that event, which
is exactly the kind of prediction this system exists not to make.

The gate blocks in both directions:

* a report inside ±``blackout_days`` of today, and
* a report falling between today and the structure's expiry — holding a short
  premium position across a print is the same mistake as opening into one.

**Unknown is not clear.** Alpaca serves no earnings calendar, so when a single
name has no entry in ``backend/data/earnings.json`` this gate fails rather than
passes. That is a deliberate, conservative default: "if market data is missing,
abstain loudly" is the house rule, and selling premium blind into an unknown
event window is precisely the failure mode. ETFs are exempt because they
genuinely do not report.

Set ``EARNINGS_UNKNOWN_BLOCKS=false`` to invert that default — but read the
paragraph above first.
"""

from __future__ import annotations

from skew.gates.base import GateContext
from skew.models import Candidate, GateResult

GATE = "earnings"

# Buying premium into an event is a different trade: the risk is paying up for
# an IV crush, not being short it. Still worth flagging, but it does not block.
PREMIUM_SELLING_KINDS = ("PUT_CREDIT", "CALL_CREDIT", "IRON_CONDOR")


def earnings_gate(candidate: Candidate, ctx: GateContext) -> GateResult:
    structure = candidate.structure
    symbol = structure.symbol
    expiry = min(leg.expiry for leg in structure.legs)

    if ctx.earnings is None:
        return GateResult(
            gate=GATE,
            passed=not ctx.earnings_unknown_blocks,
            reason=(
                "No earnings calendar is loaded, so an event window cannot be ruled out. "
                "Refusing rather than guessing."
                if ctx.earnings_unknown_blocks
                else "No earnings calendar loaded; check disabled by configuration."
            ),
            detail={"status": "no_calendar"},
        )

    status = ctx.earnings.status_for(symbol)

    if status == "etf":
        return GateResult(
            gate=GATE,
            passed=True,
            reason=f"{symbol} is an index or sector ETF and does not report earnings.",
            detail={"status": "etf"},
            skipped=True,
        )

    if status == "unknown":
        selling = structure.kind in PREMIUM_SELLING_KINDS
        if ctx.earnings_unknown_blocks and selling:
            return GateResult(
                gate=GATE,
                passed=False,
                reason=(
                    f"No confirmed earnings date for {symbol}, and this structure is short "
                    f"premium through {expiry:%d %b}. Alpaca serves no earnings calendar, "
                    f"so the window cannot be ruled out — refusing to sell volatility blind "
                    f"into a possible event."
                ),
                detail={"status": "unknown", "expiry": expiry.isoformat()},
            )
        return GateResult(
            gate=GATE,
            passed=True,
            reason=(
                f"No confirmed earnings date for {symbol}. This structure is long premium, "
                f"so an event window is a cost risk rather than a short-volatility risk."
                if selling is False
                else f"No confirmed earnings date for {symbol}; check disabled by configuration."
            ),
            detail={"status": "unknown", "blocking_disabled": not ctx.earnings_unknown_blocks},
        )

    hit = ctx.earnings.in_window(
        symbol, ctx.earnings_blackout_days, as_of=ctx.as_of, through=expiry
    )
    if hit is not None:
        days = (hit - ctx.as_of).days
        when = f"in {days} days" if days > 0 else f"{abs(days)} days ago"
        confidence = ctx.earnings.confidence_for(symbol, hit)
        # An estimated date blocks exactly like a confirmed one — a probable
        # event window is still an event window — but the copy says which it is
        # rather than claiming more certainty than the data has.
        qualifier = "reports" if confidence == "confirmed" else "is estimated to report"
        return GateResult(
            gate=GATE,
            passed=False,
            reason=(
                f"{symbol} {qualifier} on {hit:%d %b} ({when}), inside the "
                f"{ctx.earnings_blackout_days}-day blackout or before this structure expires "
                f"on {expiry:%d %b}. Implied vol is elevated for a known event and will "
                f"crush on the print — that premium is not the variance risk premium."
            ),
            detail={
                "earnings_date": hit.isoformat(),
                "days_away": days,
                "confidence": confidence,
                "source": ctx.earnings.source_for(symbol, hit),
                "blackout_days": ctx.earnings_blackout_days,
                "expiry": expiry.isoformat(),
            },
        )

    next_date = ctx.earnings.next_earnings(symbol, as_of=ctx.as_of)
    if next_date:
        confidence = ctx.earnings.confidence_for(symbol, next_date)
        tail = f"Next report {next_date:%d %b} ({confidence}), after expiry."
    else:
        tail = "No report scheduled."
    return GateResult(
        gate=GATE,
        passed=True,
        reason=f"No earnings for {symbol} before this structure expires on {expiry:%d %b}. {tail}",
        detail={
            "next_earnings": next_date.isoformat() if next_date else None,
            "confidence": ctx.earnings.confidence_for(symbol, next_date) if next_date else None,
            "expiry": expiry.isoformat(),
        },
    )


earnings_gate.gate_name = GATE  # type: ignore[attr-defined]
