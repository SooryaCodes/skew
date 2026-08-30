"""Budget gate — three separate limits, each named when it refuses.

1. **Per-trade cap** — the structure's own max loss must fit the tier's
   per-trade budget (tier 0: 0.5% of equity).
2. **Portfolio cap** — committed risk plus this structure's max loss must fit
   the tier's deployed budget (tier 0: 1.5% of equity).
3. **Position count** — the concurrent-position cap.

These used to be one number, and the conflation locked the desk out: with $341
committed against a $500 "budget", every candidate over $159 was refused
forever — sixty-four consecutive identical refusals. Per-trade risk asks "is
this position too big?"; portfolio risk asks "are we carrying too much in
total?". Different questions, different caps, and the refusal copy says which
one failed.
"""

from __future__ import annotations

from skew.gates.base import GateContext
from skew.models import Candidate, GateResult

GATE = "budget"


def budget_gate(candidate: Candidate, ctx: GateContext) -> GateResult:
    structure = candidate.structure
    risk = ctx.risk
    max_loss = structure.max_loss

    # 3 — capacity first: it is the cheapest to explain.
    if ctx.open_positions >= ctx.max_concurrent_positions:
        return GateResult(
            gate=GATE,
            passed=False,
            reason=(
                f"Already holding {ctx.open_positions} of a maximum "
                f"{ctx.max_concurrent_positions} concurrent positions. Capacity, not "
                f"conviction, is the binding constraint here."
            ),
            detail={
                "failed_check": "capacity",
                "open_positions": ctx.open_positions,
                "max_concurrent": ctx.max_concurrent_positions,
            },
        )

    # 1 — per-trade: is this single position too big for the tier?
    if max_loss > risk.budget_dollars:
        return GateResult(
            gate=GATE,
            passed=False,
            reason=(
                f"Per-trade cap — max loss ${max_loss:,.0f} exceeds the tier {risk.tier} "
                f"limit of ${risk.budget_dollars:,.0f} per position "
                f"({risk.max_loss_pct:.1%} of ${risk.equity:,.0f} equity)."
            ),
            detail={
                "failed_check": "per_trade",
                "max_loss": max_loss,
                "per_trade_cap": risk.budget_dollars,
                "tier": risk.tier,
            },
        )

    # 2 — portfolio: would total deployed risk exceed what the tier permits?
    proposed_total = risk.used_dollars + max_loss
    if proposed_total > risk.portfolio_cap_dollars:
        return GateResult(
            gate=GATE,
            passed=False,
            reason=(
                f"Portfolio cap — ${risk.used_dollars:,.0f} is already committed to open "
                f"positions, and adding this ${max_loss:,.0f} would deploy "
                f"${proposed_total:,.0f} against the tier {risk.tier} portfolio limit of "
                f"${risk.portfolio_cap_dollars:,.0f} ({risk.portfolio_pct:.1%} of equity). "
                f"The position fits the per-trade cap; the book does not have room for it."
            ),
            detail={
                "failed_check": "portfolio",
                "max_loss": max_loss,
                "committed": risk.used_dollars,
                "proposed_total": round(proposed_total, 2),
                "portfolio_cap": risk.portfolio_cap_dollars,
                "tier": risk.tier,
            },
        )

    per_trade_use = max_loss / risk.budget_dollars if risk.budget_dollars else 0.0
    return GateResult(
        gate=GATE,
        passed=True,
        reason=(
            f"Max loss ${max_loss:,.0f} is {per_trade_use:.0%} of the ${risk.budget_dollars:,.0f} "
            f"per-trade cap, and total deployed risk becomes ${proposed_total:,.0f} of the "
            f"${risk.portfolio_cap_dollars:,.0f} portfolio cap. "
            f"Position {ctx.open_positions + 1} of {ctx.max_concurrent_positions}."
        ),
        detail={
            "max_loss": max_loss,
            "per_trade_cap": risk.budget_dollars,
            "per_trade_utilisation": round(per_trade_use, 4),
            "committed": risk.used_dollars,
            "proposed_total": round(proposed_total, 2),
            "portfolio_cap": risk.portfolio_cap_dollars,
            "tier": risk.tier,
        },
    )


budget_gate.gate_name = GATE  # type: ignore[attr-defined]
