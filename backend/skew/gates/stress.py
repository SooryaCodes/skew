"""Stress gate — the one that makes the demo turn.

Builds the 84-cell scenario grid for this exact structure and applies two
checks. Read the module docstring in ``skew/stress/scenarios.py`` first: it
explains, with the arithmetic, why the second check is the one that does work.

1. **Absolute breach.** No cell may lose more than the tier budget. This is the
   invariant, and it binds for size and for any multi-expiry structure. For a
   plain vertical it coincides with the max loss, so on its own it would just
   restate the budget gate.

2. **Routine-move check.** A move of ±``routine_sigma`` — an ordinary week, not
   a tail — must not already reach more than ``routine_max_loss_pct`` of the
   structure's own max loss.

   Measured against the max loss rather than the budget, deliberately. Against
   the budget the check goes slack exactly when it matters least (a small
   position under a large budget can never reach the limit) and it would say
   nothing about the structure itself. Against the max loss it asks the question
   that matters: **how far out are the strikes, in units of what this underlying
   actually moves?** Two spreads with an identical $420 max loss are completely
   different risks if one's short strike sits half a sigma away and the other's
   two and a half, and only the grid can tell them apart.

The breaching cell's coordinates go into ``detail`` so the UI can light it up.
"""

from __future__ import annotations

from skew.gates.base import GateContext
from skew.models import Candidate, GateResult
from skew.stress.scenarios import (
    GRID_SIZE,
    breached_cells,
    build_grid,
    describe_cell,
    worst_cell,
    worst_within,
)

GATE = "stress"


def stress_gate(candidate: Candidate, ctx: GateContext) -> GateResult:
    structure = candidate.structure
    budget = ctx.risk.budget_dollars

    if budget <= 0:
        return GateResult(
            gate=GATE,
            passed=False,
            reason=(
                f"Risk budget is ${budget:,.2f} — there is no room for a new position at "
                f"tier {ctx.risk.tier}."
            ),
            detail={"budget": budget},
        )

    # Built once and hung on the candidate: the API serves it to the dashboard,
    # the MCP stress_test tool returns it, and the audit log keeps it.
    grid = build_grid(
        structure,
        realized_vol=ctx.realized_vol,
        budget=budget,
        rate=ctx.risk_free_rate,
    )
    candidate.stress_grid = grid

    worst = worst_cell(grid)
    if worst is None:
        return GateResult(
            gate=GATE,
            passed=False,
            reason="Stress grid could not be built. Refusing rather than assuming safety.",
            detail={},
        )

    candidate.worst_case = worst.pnl
    breaches = breached_cells(grid)
    routine = worst_within(grid, ctx.routine_sigma)
    routine_limit = structure.max_loss * ctx.routine_max_loss_pct

    base_detail = {
        "worst_pnl": worst.pnl,
        "worst_cell": {
            "price_shock": worst.price_shock,
            "iv_shock": worst.iv_shock,
            "time_point": worst.time_point,
        },
        "budget": budget,
        "grid_size": GRID_SIZE,
        "max_loss": structure.max_loss,
        "routine_sigma": ctx.routine_sigma,
        "routine_limit": round(routine_limit, 2),
        "routine_max_loss_pct": ctx.routine_max_loss_pct,
        "routine_pnl": routine.pnl if routine else None,
        "routine_cell": (
            {
                "price_shock": routine.price_shock,
                "iv_shock": routine.iv_shock,
                "time_point": routine.time_point,
            }
            if routine
            else None
        ),
    }

    # --- check 1: the absolute invariant ---
    if breaches:
        return GateResult(
            gate=GATE,
            passed=False,
            reason=(
                f"Worst case −${abs(worst.pnl):,.0f} at {describe_cell(worst)}, exceeds tier "
                f"{ctx.risk.tier} budget ${budget:,.0f}. "
                f"{len(breaches)} of {GRID_SIZE} scenarios breach."
            ),
            detail={**base_detail, "breached_count": len(breaches), "failed_check": "absolute"},
        )

    # --- check 2: the one that does work ---
    if routine is not None and abs(routine.pnl) > routine_limit:
        pct_of_max = abs(routine.pnl) / structure.max_loss if structure.max_loss else 0.0
        return GateResult(
            gate=GATE,
            passed=False,
            reason=(
                f"Strikes are too close to the money. An ordinary "
                f"{ctx.routine_sigma:g}σ move — {describe_cell(routine)} — already loses "
                f"−${abs(routine.pnl):,.0f}, {pct_of_max:.0%} of the "
                f"${structure.max_loss:,.0f} max loss, against a "
                f"{ctx.routine_max_loss_pct:.0%} limit. The max loss fits the budget; "
                f"the path to it is too easy."
            ),
            detail={**base_detail, "breached_count": 0, "failed_check": "routine_move"},
        )

    routine_text = (
        f"a routine {ctx.routine_sigma:g}σ move costs −${abs(routine.pnl):,.0f}, "
        f"{abs(routine.pnl) / structure.max_loss:.0%} of the max loss"
        if routine and structure.max_loss
        else "no routine-move cell available"
    )
    return GateResult(
        gate=GATE,
        passed=True,
        reason=(
            f"Survives all {GRID_SIZE} scenarios. Worst case −${abs(worst.pnl):,.0f} at "
            f"{describe_cell(worst)}, inside the tier {ctx.risk.tier} budget of "
            f"${budget:,.0f}, and {routine_text}."
        ),
        detail={
            **base_detail,
            "breached_count": 0,
            "headroom": round(budget - abs(worst.pnl), 2),
        },
    )


stress_gate.gate_name = GATE  # type: ignore[attr-defined]
