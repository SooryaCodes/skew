"""Black-Scholes and the scenario grid.

docs/07-TESTING.md: "Black-Scholes repricing against published reference values.
Off-by-one on time-to-expiry in years is the classic bug."

The canonical textbook case — S=100, K=100, T=1, r=5%, sigma=20% — prices a call
at 10.4506 and a put at 5.5735. Both are asserted below to four decimal places,
and put-call parity is asserted independently so an error in one would have to be
matched exactly by an error in the other to slip through.
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from skew.models import Leg, StressCell
from skew.stress.reprice import (
    bs_delta,
    bs_price,
    entry_value,
    expiry_pnl,
    intrinsic_value,
    norm_cdf,
    structure_pnl,
)
from skew.stress.scenarios import (
    GRID_SIZE,
    IV_SHOCKS,
    PRICE_SHOCKS,
    TIME_POINTS,
    breached_cells,
    build_grid,
    describe_cell,
    shocked_spot,
    worst_cell,
    years_at,
)
from skew.structures.base import assemble

EXPIRY = date(2026, 9, 30)


def _leg(strike, side, right, mid, iv=0.20, ratio=1) -> Leg:
    return Leg(
        symbol=f"SPY{EXPIRY:%y%m%d}{right[0]}{round(strike * 1000):08d}",
        side=side,
        position_intent="STO" if side == "SELL" else "BTO",
        ratio_qty=ratio,
        strike=strike,
        expiry=EXPIRY,
        right=right,
        mid=mid,
        iv=iv,
        delta=0.0,
        gamma=0.0,
        theta=0.0,
        vega=0.0,
        bid=mid - 0.05,
        ask=mid + 0.05,
        open_interest=5000,
    )


@pytest.fixture
def primer_spread():
    """The 580/575 put credit spread for $0.80, from docs/04-OPTIONS-PRIMER.md §5."""
    return assemble(
        "SPY",
        "PUT_CREDIT",
        [_leg(580, "SELL", "PUT", 2.00), _leg(575, "BUY", "PUT", 1.20)],
        spot=590.0,
        as_of=date(2026, 8, 30),
    )


# ====================================================================
# Black-Scholes against published reference values
# ====================================================================


def test_normal_cdf_reference_points():
    assert norm_cdf(0.0) == pytest.approx(0.5, abs=1e-12)
    assert norm_cdf(1.0) == pytest.approx(0.8413447461, abs=1e-9)
    assert norm_cdf(-1.96) == pytest.approx(0.0249978952, abs=1e-9)
    assert norm_cdf(1.645) == pytest.approx(0.9500150944, abs=1e-9)


def test_black_scholes_textbook_call():
    """S=100 K=100 T=1 r=5% sigma=20% -> 10.4506. The canonical reference."""
    assert bs_price(100, 100, 1.0, 0.20, "CALL", rate=0.05) == pytest.approx(10.4506, abs=1e-4)


def test_black_scholes_textbook_put():
    """Same inputs -> 5.5735."""
    assert bs_price(100, 100, 1.0, 0.20, "PUT", rate=0.05) == pytest.approx(5.5735, abs=1e-4)


@pytest.mark.parametrize(
    ("spot", "strike", "years", "vol", "rate", "call", "put"),
    [
        (100, 100, 1.0, 0.20, 0.05, 10.4506, 5.5735),
        (100, 110, 1.0, 0.20, 0.05, 6.0401, 10.6753),
        # The two below are cross-checked by put-call parity in the assertion
        # itself, so they cannot both drift without the identity failing.
        (100, 90, 0.5, 0.30, 0.05, 15.4860, 3.2639),
        (50, 50, 0.25, 0.40, 0.03, 4.1575, 3.7839),
    ],
)
def test_black_scholes_reference_grid(spot, strike, years, vol, rate, call, put):
    got_call = bs_price(spot, strike, years, vol, "CALL", rate)
    got_put = bs_price(spot, strike, years, vol, "PUT", rate)
    assert got_call == pytest.approx(call, abs=1e-3)
    assert got_put == pytest.approx(put, abs=1e-3)
    assert got_call - got_put == pytest.approx(spot - strike * math.exp(-rate * years), abs=1e-9)


def test_put_call_parity_holds():
    """C − P = S − K·e^(−rT). Independent of the pricing formula being right, so
    it catches an error that happened to be symmetric."""
    s, k, t, v, r = 123.45, 130.0, 0.37, 0.28, 0.042
    call = bs_price(s, k, t, v, "CALL", r)
    put = bs_price(s, k, t, v, "PUT", r)
    assert call - put == pytest.approx(s - k * math.exp(-r * t), abs=1e-9)


def test_time_to_expiry_must_be_years_not_days():
    """The classic bug. 30 days is 0.0822 years, and passing 30 instead prices a
    one-month option as a thirty-year one — off by more than a factor of ten."""
    as_years = bs_price(100, 100, 30 / 365, 0.20, "CALL", 0.05)
    as_days = bs_price(100, 100, 30.0, 0.20, "CALL", 0.05)
    assert as_years == pytest.approx(2.4934, abs=1e-3)
    # 30 "years" prices an at-the-money call at ~80% of spot. Wildly wrong, and
    # visibly so — which is the point of pinning it.
    assert as_days == pytest.approx(79.5141, abs=1e-3)
    assert as_days / as_years > 30


def test_zero_time_collapses_to_intrinsic_value():
    """The stress grid evaluates the expiry column, so this path is hot."""
    assert bs_price(110, 100, 0.0, 0.20, "CALL") == pytest.approx(10.0)
    assert bs_price(90, 100, 0.0, 0.20, "CALL") == pytest.approx(0.0)
    assert bs_price(90, 100, 0.0, 0.20, "PUT") == pytest.approx(10.0)
    assert bs_price(110, 100, 0.0, 0.20, "PUT") == pytest.approx(0.0)


def test_zero_volatility_does_not_produce_nan():
    """A NaN here would silently poison the worst case the gate depends on."""
    for right in ("CALL", "PUT"):
        price = bs_price(100, 95, 0.5, 0.0, right)
        assert math.isfinite(price)
        assert price == pytest.approx(intrinsic_value(100, 95, right))


def test_price_is_monotonic_in_volatility():
    prices = [bs_price(100, 100, 0.5, v, "CALL", 0.05) for v in (0.1, 0.2, 0.4, 0.8)]
    assert prices == sorted(prices)


def test_deltas_have_the_right_signs_and_bounds():
    assert 0.0 <= bs_delta(100, 100, 0.5, 0.2, "CALL") <= 1.0
    assert -1.0 <= bs_delta(100, 100, 0.5, 0.2, "PUT") <= 0.0
    assert bs_delta(100, 100, 0.5, 0.2, "CALL") == pytest.approx(
        bs_delta(100, 100, 0.5, 0.2, "PUT") + 1.0, abs=1e-9
    )


# ====================================================================
# P&L, worked through by hand
# ====================================================================


def test_entry_value_is_minus_the_credit(primer_spread):
    """Taking in $80 of credit means the position starts as an $80 liability."""
    assert entry_value(primer_spread) == pytest.approx(-80.0)
    assert entry_value(primer_spread) == pytest.approx(-primer_spread.net_credit)


def test_expiry_pnl_max_profit_when_both_legs_expire_worthless(primer_spread):
    """SPY above 580: both puts worthless, we keep the $80."""
    assert expiry_pnl(primer_spread, 600.0) == pytest.approx(80.0)
    assert expiry_pnl(primer_spread, 580.0) == pytest.approx(80.0)


def test_expiry_pnl_max_loss_below_the_long_strike(primer_spread):
    """SPY at 570: short put worth $10, long worth $5.

    value = (−10 + 5) × 100 = −500, P&L = −500 + 80 = −$420 — the max loss.
    """
    assert expiry_pnl(primer_spread, 570.0) == pytest.approx(-420.0)
    assert expiry_pnl(primer_spread, 500.0) == pytest.approx(-420.0)
    assert expiry_pnl(primer_spread, 570.0) == pytest.approx(-primer_spread.max_loss)


def test_expiry_pnl_at_the_breakeven_is_zero(primer_spread):
    """Breakeven 579.20 was computed independently in structures/base.py."""
    assert expiry_pnl(primer_spread, primer_spread.breakevens[0]) == pytest.approx(0.0, abs=1e-6)


def test_expiry_pnl_between_the_strikes_is_linear(primer_spread):
    """Halfway between 575 and 580, half the width is lost."""
    assert expiry_pnl(primer_spread, 577.5) == pytest.approx(80.0 - 250.0)


def test_pnl_never_worse_than_max_loss_at_expiry(primer_spread):
    for spot in range(400, 800, 5):
        assert expiry_pnl(primer_spread, float(spot)) >= -primer_spread.max_loss - 1e-6


def test_unchanged_market_gives_exactly_zero_pnl():
    """Repricing at entry conditions must recover the entry price exactly.

    Built with Black-Scholes-consistent mids so the identity is exact rather
    than approximate. If this drifts, entry_value and structure_value have
    diverged and every P&L in the grid is offset by a constant.
    """
    spot, years, iv = 590.0, 31 / 365, 0.20
    short_mid = bs_price(spot, 580.0, years, iv, "PUT", 0.042)
    long_mid = bs_price(spot, 575.0, years, iv, "PUT", 0.042)
    s = assemble(
        "SPY",
        "PUT_CREDIT",
        [_leg(580, "SELL", "PUT", short_mid, iv), _leg(575, "BUY", "PUT", long_mid, iv)],
        spot=spot,
        as_of=date(2026, 8, 30),
    )
    assert structure_pnl(s, spot, years, 1.0, 0.042) == pytest.approx(0.0, abs=1e-6)


# ====================================================================
# The grid
# ====================================================================


def test_grid_is_exactly_84_cells(primer_spread):
    assert GRID_SIZE == 84
    assert len(PRICE_SHOCKS) == 7
    assert len(IV_SHOCKS) == 4
    assert len(TIME_POINTS) == 3

    grid = build_grid(primer_spread, realized_vol=0.15, budget=1000.0)
    assert len(grid) == 84
    assert len({(c.price_shock, c.iv_shock, c.time_point) for c in grid}) == 84


def test_grid_shocks_match_the_specification():
    assert PRICE_SHOCKS == (-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0)
    assert IV_SHOCKS == (0.7, 1.0, 1.5, 2.0)
    assert TIME_POINTS == ("NOW", "MID", "EXPIRY")


def test_years_at_each_time_point():
    assert years_at("NOW", 30) == pytest.approx(30 / 365)
    assert years_at("MID", 30) == pytest.approx(15 / 365)
    assert years_at("EXPIRY", 30) == 0.0


def test_shocked_spot_cannot_go_negative():
    """A −3σ shock on a high-vol name can arithmetically take spot below zero."""
    assert shocked_spot(100.0, 0.5, -3.0) > 0
    assert shocked_spot(100.0, 0.10, 2.0) == pytest.approx(120.0)
    assert shocked_spot(100.0, 0.10, -2.0) == pytest.approx(80.0)


def test_a_generous_budget_breaches_nothing(primer_spread):
    grid = build_grid(primer_spread, realized_vol=0.15, budget=10_000.0)
    assert breached_cells(grid) == []


def test_a_tight_budget_breaches_and_identifies_the_worst_cell(primer_spread):
    grid = build_grid(primer_spread, realized_vol=0.15, budget=100.0)
    breaches = breached_cells(grid)
    assert breaches, "a $100 budget cannot survive a $420 max-loss structure"

    worst = worst_cell(grid)
    assert worst is not None and worst.breached
    assert worst.pnl <= min(c.pnl for c in grid)
    assert worst.price_shock < 0, "a short put spread is hurt by the downside"


def test_worst_case_is_never_better_than_the_expiry_max_loss(primer_spread):
    """The point of the whole engine: along the way can be worse than at expiry.

    The worst cell must be at least as bad as the terminal max loss — if the
    grid ever reported a gentler worst case than the arithmetic guarantees,
    the gate would be waving through positions it should stop.
    """
    grid = build_grid(primer_spread, realized_vol=0.30, budget=10_000.0)
    worst = worst_cell(grid)
    assert worst is not None
    assert worst.pnl <= -primer_spread.max_loss + 1e-6


def test_expiry_row_ignores_iv_shocks(primer_spread):
    """At expiry there is no time value, so IV cannot change the payoff."""
    grid = build_grid(primer_spread, realized_vol=0.15, budget=10_000.0)
    for shock in PRICE_SHOCKS:
        pnls = {c.pnl for c in grid if c.time_point == "EXPIRY" and c.price_shock == shock}
        assert len(pnls) == 1, f"IV shock changed the expiry payoff at {shock}σ"


def test_rising_iv_hurts_a_short_premium_position_while_it_still_has_time_value(
    primer_spread,
):
    """With the spread out of the money, rising IV makes it dearer to buy back.

    Checked on the upside shocks, where the structure stays out of the money.
    (Spot 590 against 580/575 strikes: even −1σ pushes past both, so the
    downside cells are the max-loss regime the sibling test covers.)
    """
    grid = build_grid(primer_spread, realized_vol=0.12, budget=10_000.0)
    lookup = {(c.price_shock, c.iv_shock, c.time_point): c.pnl for c in grid}
    for shock in (0.0, 1.0, 2.0):
        assert lookup[(shock, 2.0, "MID")] < lookup[(shock, 1.0, "MID")]
        assert lookup[(shock, 1.0, "MID")] < lookup[(shock, 0.7, "MID")]


def test_rising_iv_relieves_a_spread_that_is_already_at_max_loss(primer_spread):
    """Deep in the money, higher IV *reduces* the loss — and that is correct.

    Past both strikes the spread sits at its terminal −$420. Adding volatility
    adds time value to both legs, and more to the nearer-the-money long leg than
    to the deeper short one, so the net liability shrinks back toward the middle.

    Worth pinning precisely because it looks like a bug. The engine must model
    what options actually do, not what a rule of thumb says they do.
    """
    grid = build_grid(primer_spread, realized_vol=0.25, budget=10_000.0)
    lookup = {(c.price_shock, c.iv_shock, c.time_point): c.pnl for c in grid}
    deep = lookup[(-2.0, 2.0, "MID")]
    assert deep > lookup[(-2.0, 0.7, "MID")]
    # Still a loss, and still bounded by the structure's max loss.
    assert -primer_spread.max_loss <= deep < 0


def test_rising_iv_helps_a_long_premium_position():
    """The mirror case — a debit spread is long vega and gains when IV rises."""
    debit = assemble(
        "SPY",
        "CALL_DEBIT",
        [_leg(580, "BUY", "CALL", 6.00), _leg(590, "SELL", "CALL", 2.50)],
        spot=580.0,
        as_of=date(2026, 8, 30),
    )
    grid = build_grid(debit, realized_vol=0.20, budget=10_000.0)
    lookup = {(c.price_shock, c.iv_shock, c.time_point): c.pnl for c in grid}
    assert lookup[(0.0, 2.0, "MID")] > lookup[(0.0, 0.7, "MID")]


def test_describe_cell_reads_as_human_copy():
    cell = StressCell(price_shock=-2.0, iv_shock=2.0, time_point="MID", pnl=-1240.0, breached=True)
    assert describe_cell(cell) == "-2σ with IV +100%, halfway to expiry"

    calm = StressCell(price_shock=0.0, iv_shock=1.0, time_point="NOW", pnl=0.0, breached=False)
    assert describe_cell(calm) == "+0σ with IV unchanged, immediately"


def test_grid_builds_on_a_real_structure(real_spy_chain, real_as_of):
    from skew.structures.credit import put_credit_spread

    s = put_credit_spread(real_spy_chain, dte_min=14, dte_max=60, as_of=real_as_of)
    assert s is not None
    grid = build_grid(s, realized_vol=0.12, budget=500.0)
    assert len(grid) == 84
    assert all(math.isfinite(c.pnl) for c in grid)
    worst = worst_cell(grid)
    assert worst is not None and worst.pnl <= 0
