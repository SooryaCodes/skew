"""The scenario grid — 84 repriced outcomes per candidate.

    price shocks   −3σ, −2σ, −1σ, 0, +1σ, +2σ, +3σ        (7)
    IV shocks      ×0.7, ×1.0, ×1.5, ×2.0                 (4)
    time points    now, halfway to expiry, expiry         (3)
                                                          ──
                                                          84

σ is 20-day realized volatility scaled to days-to-expiry, so a −2σ shock is a
move the underlying could plausibly make over the life of this position rather
than an abstract percentage.

WHAT THIS ENGINE IS ACTUALLY FOR — a correction to the spec
-----------------------------------------------------------
docs/01-ARCHITECTURE.md §5 and docs/04-OPTIONS-PRIMER.md §7 both motivate this
module with "max loss is what you lose at expiry, but you can be down far more
than that along the way". For **naked or undefined-risk** positions that is true
and important. For the defined-width verticals this desk actually trades, it is
false, and provably so: a vertical's liability is bounded above by
``width × e^(−rT)``, strictly less than the width itself. The mark-to-market
loss can never exceed the terminal max loss, and the grid confirms it — for a
vertical the worst cell is always in the expiry column, exactly at max loss.

Taken at face value, that would make the stress gate a redundant restatement of
the budget gate. So the engine measures the thing that *is* additive:

    **how much of the max loss a routine move already reaches.**

Two spreads can carry an identical $420 max loss while one has its short strike
half a sigma away and the other two and a half. The first is close to a coin
flip; the second is rarely touched. Max loss cannot tell them apart. The grid
can — see :func:`worst_within`.

Both checks are applied. The absolute breach still binds for size, for
multi-expiry structures, and as the invariant that nothing can lose more than
budget. The routine-move check is the one that does work every cycle.
"""

from __future__ import annotations

from skew.models import StressCell, Structure, TimePoint
from skew.stress.reprice import expiry_pnl, structure_pnl
from skew.vol.realized import sigma_for_horizon

# The grid. Kept as module constants so the UI, the tests and the gate all
# agree on the shape without passing it around.
PRICE_SHOCKS: tuple[float, ...] = (-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0)
IV_SHOCKS: tuple[float, ...] = (0.7, 1.0, 1.5, 2.0)
TIME_POINTS: tuple[TimePoint, ...] = ("NOW", "MID", "EXPIRY")

GRID_SIZE = len(PRICE_SHOCKS) * len(IV_SHOCKS) * len(TIME_POINTS)  # 84


def shocked_spot(spot: float, sigma_move: float, shock_sigmas: float) -> float:
    """Apply a sigma shock to spot, floored above zero.

    An underlying cannot go negative, and a −3σ shock on a high-vol name can
    arithmetically take it there. Floored at 1% of spot rather than clamped to
    zero so the repricing stays numerically well behaved.
    """
    return max(spot * 0.01, spot * (1.0 + shock_sigmas * sigma_move))


def years_at(time_point: TimePoint, dte: int) -> float:
    """Time to expiry in YEARS at each of the three time points.

    Days-to-expiry over 365 — calendar time, because that is what option
    contracts decay against. (Trading-day counts belong in the volatility
    estimators, not here.)
    """
    if time_point == "NOW":
        return max(0.0, dte / 365.0)
    if time_point == "MID":
        return max(0.0, dte / 2.0 / 365.0)
    return 0.0


def build_grid(
    structure: Structure,
    realized_vol: float,
    budget: float,
    rate: float = 0.042,
) -> list[StressCell]:
    """Reprice the structure across every cell.

    ``realized_vol`` is the annualised 20-day realized volatility of the
    underlying; ``budget`` is the current risk tier's dollar limit, and a cell
    is marked breached when its loss exceeds it.

    Returns all 84 cells — including the calm ones. The UI renders the whole
    grid because a grid that is almost entirely calm is what makes the single
    red cell mean something.
    """
    # Fractional one-sigma move over the life of the position.
    sigma_move = sigma_for_horizon(realized_vol, max(structure.dte, 1))
    cells: list[StressCell] = []

    for time_point in TIME_POINTS:
        years = years_at(time_point, structure.dte)
        for price_shock in PRICE_SHOCKS:
            spot = shocked_spot(structure.spot, sigma_move, price_shock)
            for iv_shock in IV_SHOCKS:
                if time_point == "EXPIRY":
                    # At expiry there is no time value left, so an IV shock
                    # cannot change the payoff. The cells are still emitted, so
                    # the grid stays rectangular and the UI does not have to
                    # special-case a ragged final row.
                    pnl = expiry_pnl(structure, spot)
                else:
                    pnl = structure_pnl(structure, spot, years, iv_shock, rate)

                cells.append(
                    StressCell(
                        price_shock=price_shock,
                        iv_shock=iv_shock,
                        time_point=time_point,
                        pnl=round(pnl, 2),
                        breached=pnl < -abs(budget),
                    )
                )

    return cells


def worst_cell(cells: list[StressCell]) -> StressCell | None:
    """The single worst outcome across the grid."""
    return min(cells, key=lambda c: c.pnl) if cells else None


def worst_within(
    cells: list[StressCell],
    max_abs_sigma: float,
    include_expiry: bool = False,
) -> StressCell | None:
    """The worst outcome inside a *routine* move, rather than a tail one.

    This is the measurement that earns the grid its place. For a defined-width
    vertical the absolute worst case is pinned to the terminal max loss (see
    the module note below), so comparing it against the budget tells you nothing
    the budget gate did not already know. What the grid *does* know, and nothing
    else does, is **how much of that loss a routine move already reaches.**

    Two spreads can carry an identical $420 max loss while one has its short
    strike half a sigma away and the other two and a half. The first is close to
    a coin flip; the second rarely gets touched. Only the grid can tell them
    apart.

    Expiry cells are excluded by default: at expiry the payoff is the terminal
    one, and including it would collapse this back into the max-loss check.
    """
    pool = [
        c
        for c in cells
        if abs(c.price_shock) <= max_abs_sigma + 1e-9
        and (include_expiry or c.time_point != "EXPIRY")
    ]
    return min(pool, key=lambda c: c.pnl) if pool else None


def best_within(
    cells: list[StressCell],
    max_abs_sigma: float,
    include_expiry: bool = False,
) -> StressCell | None:
    """The best outcome inside a routine move — the mirror of :func:`worst_within`.

    Used for long-premium structures, where the meaningful question is inverted.
    A debit spread's maximum loss is simply the premium paid, and an adverse
    move of any size takes most of it, so asking "does a routine move reach the
    max loss" would refuse every debit spread ever built. The question that
    actually separates a good long-premium structure from a bad one is whether
    it can **profit on an ordinary move**, or whether it needs a tail event to
    come good.
    """
    pool = [
        c
        for c in cells
        if abs(c.price_shock) <= max_abs_sigma + 1e-9
        and (include_expiry or c.time_point != "EXPIRY")
    ]
    return max(pool, key=lambda c: c.pnl) if pool else None


def worst_case(cells: list[StressCell]) -> float:
    """The worst P&L across the grid. Zero when the grid is empty."""
    cell = worst_cell(cells)
    return cell.pnl if cell else 0.0


def breached_cells(cells: list[StressCell]) -> list[StressCell]:
    return [c for c in cells if c.breached]


def describe_cell(cell: StressCell) -> str:
    """Human copy for a gate reason string.

    Reads as "−2σ with IV +100%, halfway to expiry" rather than as coordinates,
    because this string goes straight into the UI.
    """
    iv_pct = (cell.iv_shock - 1.0) * 100.0
    iv_text = "IV unchanged" if abs(iv_pct) < 1e-9 else f"IV {iv_pct:+.0f}%"
    when = {"NOW": "immediately", "MID": "halfway to expiry", "EXPIRY": "at expiry"}[
        cell.time_point
    ]
    return f"{cell.price_shock:+.0f}σ with {iv_text}, {when}"
