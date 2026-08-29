"""Liquidity gate.

Rejects structures built on contracts that cannot be traded at a sane price.
Two reasons, and the second matters more than it first appears:

1. **The fill will be terrible.** Crossing a 40%-wide market on entry and again
   on exit can cost more than the edge the whole trade was built to capture.
2. **The Greeks are unreliable.** Alpaca derives implied volatility and Greeks
   from the market price. If that price is a stale, one-sided quote on a
   contract nobody trades, the IV we measured the variance risk premium against
   is not a real number — and the entire premise of the position rests on it.

Note the gap flagged in ``skew/data/chains.py``: per-contract daily volume is
not available without a bars call per contract, which is far too expensive for
a five-minute loop. This gate therefore keys on open interest, quote presence
and bid-ask width, and ``MIN_VOLUME`` defaults to 0. Documented, not faked.
"""

from __future__ import annotations

from skew.gates.base import GateContext
from skew.models import Candidate, GateResult

GATE = "liquidity"


def liquidity_gate(candidate: Candidate, ctx: GateContext) -> GateResult:
    structure = candidate.structure
    worst_oi = min((leg.open_interest for leg in structure.legs), default=0)
    worst_spread_leg = max(structure.legs, key=lambda leg: leg.spread_pct)
    worst_spread = worst_spread_leg.spread_pct

    unquoted = [leg for leg in structure.legs if leg.bid <= 0 or leg.ask <= 0]
    if unquoted:
        names = ", ".join(leg.symbol for leg in unquoted)
        return GateResult(
            gate=GATE,
            passed=False,
            reason=(
                f"No two-sided market on {names}. A leg with no bid cannot be closed, "
                f"so the position would be defined-risk on paper only."
            ),
            detail={"unquoted": [leg.symbol for leg in unquoted]},
        )

    if worst_oi < ctx.min_open_interest:
        thin = min(structure.legs, key=lambda leg: leg.open_interest)
        return GateResult(
            gate=GATE,
            passed=False,
            reason=(
                f"Open interest {worst_oi:,} on {thin.symbol} is below the "
                f"{ctx.min_open_interest:,} floor. Thin contracts fill badly and their "
                f"quoted IV is not a reliable measurement."
            ),
            detail={
                "worst_open_interest": worst_oi,
                "threshold": ctx.min_open_interest,
                "contract": thin.symbol,
            },
        )

    if worst_spread > ctx.max_spread_pct:
        return GateResult(
            gate=GATE,
            passed=False,
            reason=(
                f"Bid-ask spread {worst_spread:.1%} of mid on {worst_spread_leg.symbol} "
                f"exceeds the {ctx.max_spread_pct:.0%} limit "
                f"(${worst_spread_leg.bid:.2f} / ${worst_spread_leg.ask:.2f}). "
                f"Crossing that twice costs more than the edge."
            ),
            detail={
                "worst_spread_pct": round(worst_spread, 4),
                "threshold": ctx.max_spread_pct,
                "contract": worst_spread_leg.symbol,
                "bid": worst_spread_leg.bid,
                "ask": worst_spread_leg.ask,
            },
        )

    if ctx.min_volume > 0:
        worst_volume = min((leg.volume for leg in structure.legs), default=0)
        if worst_volume < ctx.min_volume:
            return GateResult(
                gate=GATE,
                passed=False,
                reason=(f"Daily volume {worst_volume:,} is below the {ctx.min_volume:,} floor."),
                detail={"worst_volume": worst_volume, "threshold": ctx.min_volume},
            )

    return GateResult(
        gate=GATE,
        passed=True,
        reason=(
            f"Liquid — open interest {worst_oi:,} on the thinnest leg, widest spread "
            f"{worst_spread:.1%} of mid, all {len(structure.legs)} legs two-sided."
        ),
        detail={
            "worst_open_interest": worst_oi,
            "worst_spread_pct": round(worst_spread, 4),
        },
    )


liquidity_gate.gate_name = GATE  # type: ignore[attr-defined]
