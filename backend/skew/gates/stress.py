"""Stress gate — the one that makes the demo turn.

Builds the 84-cell scenario grid for this exact structure and applies two
checks. Read the module docstring in ``skew/stress/scenarios.py`` first: it
explains, with the arithmetic, why the second check is the one that does work.

1. **Absolute breach.** No cell may lose more than the tier budget. This is the
   invariant, and it binds for size and for any multi-expiry structure. For a
   plain vertical it coincides with the max loss, so on its own it would just
   restate the budget gate.

2. **Routine-move check**, and it asks a different question of each side.

   *Short premium* — a move of ±``routine_sigma``, an ordinary week rather than
   a tail, must not already reach more than ``routine_max_loss_pct`` of the
   structure's own max loss. Measured against max loss rather than budget,
   deliberately: against the budget the check goes slack exactly when it matters
   least, and it would say nothing about the structure itself. Against max loss
   it asks the question that matters — **how far out are the strikes, in units
   of what this underlying actually moves?** Two spreads with an identical $420
   max loss are completely different risks if one's short strike sits half a
   sigma away and the other's two and a half.

   *Long premium* — the same test would refuse every debit spread ever built.
   A debit spread's max loss is just the premium paid, and an adverse move of
   any size takes 80–100% of it at every level of realized volatility; that is
   the structure working as designed, not a defect. So the question is inverted
   and measured differently: **how far must the underlying travel, in sigma,
   before this position breaks even?** A debit spread whose breakeven sits two
   sigma away is a lottery ticket; one whose breakeven sits half a sigma away is
   a volatility position. Measured on the breakeven rather than on the grid,
   because a long-vega structure profits from an IV shock alone and that would
   mask a strike that price can never reach.

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
from skew.vol.realized import sigma_for_horizon

GATE = "stress"

# The routine-move check asks the opposite question of these than of the rest.
PREMIUM_SELLING_KINDS = ("PUT_CREDIT", "CALL_CREDIT", "IRON_CONDOR")


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
    selling = structure.kind in PREMIUM_SELLING_KINDS
    routine = worst_within(grid, ctx.routine_sigma)
    routine_limit = structure.max_loss * ctx.routine_max_loss_pct

    # How far the underlying typically travels over the life of this position.
    sigma_move = sigma_for_horizon(ctx.realized_vol, max(structure.dte, 1))
    nearest_breakeven = (
        min(structure.breakevens, key=lambda b: abs(b - structure.spot))
        if structure.breakevens
        else structure.spot
    )
    breakeven_sigma = (
        abs(nearest_breakeven - structure.spot) / (structure.spot * sigma_move)
        if sigma_move > 0 and structure.spot > 0
        else None
    )

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
        "short_premium": structure.kind in PREMIUM_SELLING_KINDS,
        "breakeven_sigma": round(breakeven_sigma, 3) if breakeven_sigma is not None else None,
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

    # --- check 2a: short premium — are the strikes far enough out? ---
    if selling and routine is not None and abs(routine.pnl) > routine_limit:
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

    # --- check 2b: long premium — how far must price travel to break even? ---
    if not selling and breakeven_sigma is not None and breakeven_sigma > ctx.max_breakeven_sigma:
        return GateResult(
            gate=GATE,
            passed=False,
            reason=(
                f"Breakeven is {breakeven_sigma:.1f}σ away, past the "
                f"{ctx.max_breakeven_sigma:g}σ limit. At {ctx.realized_vol * 100:.0f} realized "
                f"vol the underlying moves about {sigma_move * structure.spot:,.2f} over "
                f"{structure.dte} days, and this structure needs "
                f"{abs(nearest_breakeven - structure.spot):,.2f}. That is a lottery ticket, "
                f"not a volatility position."
            ),
            detail={**base_detail, "breached_count": 0, "failed_check": "breakeven_too_far"},
        )

    if selling and routine and structure.max_loss:
        routine_text = (
            f"a routine {ctx.routine_sigma:g}σ move costs −${abs(routine.pnl):,.0f}, "
            f"{abs(routine.pnl) / structure.max_loss:.0%} of the max loss"
        )
    elif not selling and breakeven_sigma is not None:
        routine_text = f"breakeven sits {breakeven_sigma:.1f}σ away, inside the routine range"
    else:
        routine_text = "no routine-move cell available"
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
