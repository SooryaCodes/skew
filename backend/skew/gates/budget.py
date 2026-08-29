"""Budget gate — the structure's max loss must fit inside the earned tier.

The last gate in the chain, and the simplest. Where the stress gate asks "could
this position hurt more than the budget along the way", this one asks the
straightforward question: is the known, terminal maximum loss inside what this
desk has currently earned the right to risk?

It also enforces the concurrent-position cap, because three positions each
inside budget individually can still add up to a portfolio nobody authorised.
"""

from __future__ import annotations

from skew.gates.base import GateContext
from skew.models import Candidate, GateResult

GATE = "budget"


def budget_gate(candidate: Candidate, ctx: GateContext) -> GateResult:
    structure = candidate.structure
    risk = ctx.risk
    max_loss = structure.max_loss

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
                "open_positions": ctx.open_positions,
                "max_concurrent": ctx.max_concurrent_positions,
            },
        )

    if max_loss > risk.budget_dollars:
        return GateResult(
            gate=GATE,
            passed=False,
            reason=(
                f"Max loss ${max_loss:,.0f} exceeds the tier {risk.tier} budget of "
                f"${risk.budget_dollars:,.0f} "
                f"({risk.max_loss_pct:.1%} of ${risk.equity:,.0f} equity). "
                f"{risk.next_promotion}"
            ),
            detail={
                "max_loss": max_loss,
                "budget": risk.budget_dollars,
                "tier": risk.tier,
                "max_loss_pct": risk.max_loss_pct,
            },
        )

    if max_loss > risk.available_dollars:
        return GateResult(
            gate=GATE,
            passed=False,
            reason=(
                f"Max loss ${max_loss:,.0f} fits the tier {risk.tier} budget of "
                f"${risk.budget_dollars:,.0f}, but ${risk.used_dollars:,.0f} is already "
                f"committed to open positions, leaving ${risk.available_dollars:,.0f}."
            ),
            detail={
                "max_loss": max_loss,
                "budget": risk.budget_dollars,
                "used": risk.used_dollars,
                "available": risk.available_dollars,
            },
        )

    utilisation = max_loss / risk.budget_dollars if risk.budget_dollars else 0.0
    return GateResult(
        gate=GATE,
        passed=True,
        reason=(
            f"Max loss ${max_loss:,.0f} is {utilisation:.0%} of the tier {risk.tier} budget "
            f"(${risk.budget_dollars:,.0f}, {risk.max_loss_pct:.1%} of equity). "
            f"Position {ctx.open_positions + 1} of {ctx.max_concurrent_positions}."
        ),
        detail={
            "max_loss": max_loss,
            "budget": risk.budget_dollars,
            "utilisation": round(utilisation, 4),
            "tier": risk.tier,
        },
    )


budget_gate.gate_name = GATE  # type: ignore[attr-defined]
