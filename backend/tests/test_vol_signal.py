"""Implied vol extraction, term structure, ranks, and the VRP regime classifier.

The regime classifier is tested at every boundary, per docs/PHASE-01. It is the
gate between "we have data" and "we will trade", and an off-by-one on a boundary
here means the desk trades in a regime it was explicitly designed to sit out.
"""

from __future__ import annotations

import numpy as np
import pytest

from skew.config import Settings
from skew.vol.implied import atm_implied_vol, iv_at_delta, skew_slice, skew_steepness
from skew.vol.rank import iv_rank_from_history, percentile_of, range_rank, rv_percentile
from skew.vol.realized import close_to_close_vol
from skew.vol.term import term_structure_slope
from skew.vol.vrp import (
    RV_PERCENTILE_CEILING,
    VOL_POINT,
    build_vol_state,
    classify_regime,
    variance_risk_premium,
)

# ------------------------------------------------------------------ implied


def test_atm_iv_from_a_real_chain(real_spy_chain, real_as_of):
    atm = atm_implied_vol(real_spy_chain, target_dte=30, as_of=real_as_of)
    assert atm is not None
    assert 0.02 < atm.iv < 2.0, "ATM IV outside 2%–200% means a units bug"
    assert atm.dte > 0
    assert atm.call_iv is not None and atm.put_iv is not None
    # Put-call parity: at the money the two IVs should be close.
    assert abs(atm.call_iv - atm.put_iv) < 0.10


def test_atm_iv_matches_the_known_synthetic_surface(calm_chain, calm_as_of):
    """The synthetic surface is ATM 15.8% at 30 DTE, in contango.

    Recovering that number end-to-end proves the interpolation, the call/put
    average and the expiry selection all line up.
    """
    atm = atm_implied_vol(calm_chain, target_dte=30, as_of=calm_as_of)
    assert atm is not None
    assert atm.iv == pytest.approx(0.158, abs=0.01)


def test_atm_iv_interpolates_between_bracketing_strikes(calm_chain, calm_as_of):
    """Spot rarely sits on a strike. Taking the nearest one is biased."""
    atm = atm_implied_vol(calm_chain, target_dte=30, as_of=calm_as_of)
    assert atm is not None and atm.interpolated


def test_atm_iv_returns_none_rather_than_zero_on_an_empty_chain():
    from skew.data.chains import OptionChain

    assert atm_implied_vol(OptionChain(symbol="SPY", spot=100.0)) is None


def test_skew_curve_is_downward_sloping(real_spy_chain, real_as_of):
    """Lower strikes carry higher IV, because people pay up for downside
    protection. That asymmetry is the skew, and it is what the product is named
    after — if this ever inverts, the curve in the header is wrong."""
    points = skew_slice(real_spy_chain, target_dte=30, as_of=real_as_of)
    assert len(points) > 8

    strikes = np.array([p.strike for p in points])
    ivs = np.array([p.iv for p in points])
    assert np.all(np.diff(strikes) > 0), "points must be sorted by strike"
    slope = np.polyfit(strikes, ivs, 1)[0]
    assert slope < 0, "IV should fall as strike rises"


def test_skew_curve_uses_otm_contracts_only(real_spy_chain, real_as_of):
    """In-the-money options are thinly quoted; including them puts a kink in the
    curve that is an artefact of the data, not a property of the market."""
    points = skew_slice(real_spy_chain, target_dte=30, as_of=real_as_of)
    spot = real_spy_chain.spot
    for p in points:
        if p.right == "PUT":
            assert p.strike <= spot
        else:
            assert p.strike > spot


def test_skew_steepness_positive_in_normal_market(real_spy_chain, real_as_of):
    points = skew_slice(real_spy_chain, target_dte=30, width_pct=0.12, as_of=real_as_of)
    assert skew_steepness(points, real_spy_chain.spot) > 0


def test_iv_at_delta_selects_by_delta_not_distance(real_spy_chain, real_as_of):
    expiry = real_spy_chain.nearest_expiry(30, as_of=real_as_of)
    assert expiry is not None
    c = iv_at_delta(real_spy_chain, expiry, "PUT", 0.25)
    assert c is not None
    assert abs(abs(c.delta) - 0.25) < 0.12
    assert c.delta < 0, "a put's delta is negative; comparison must be on absolutes"


# ------------------------------------------------------------------ term


def test_term_structure_in_contango_on_the_calm_fixture(calm_chain, calm_as_of):
    term = term_structure_slope(calm_chain, as_of=calm_as_of)
    assert term is not None
    assert term.is_contango and not term.is_backwardation
    assert term.slope > 0
    assert term.far_dte > term.near_dte
    assert "contango" in term.describe()


def test_term_structure_detects_backwardation(stressed_chain, calm_as_of):
    """The market is scared right now. This must be unmistakable."""
    term = term_structure_slope(stressed_chain, as_of=calm_as_of)
    assert term is not None
    assert term.is_backwardation
    assert term.slope < 0
    assert term.near_iv > term.far_iv
    assert term.shape == "backwardation"


def test_real_chain_term_structure_computes(real_spy_chain, real_as_of):
    term = term_structure_slope(real_spy_chain, as_of=real_as_of)
    assert term is not None
    assert len(term.points) >= 2
    assert all(0.0 < p.iv_atm < 3.0 for p in term.points)


def test_term_structure_none_with_fewer_than_two_expiries():
    from skew.data.chains import OptionChain

    assert term_structure_slope(OptionChain(symbol="SPY", spot=100.0)) is None


def test_flat_curve_is_neither_contango_nor_backwardation(calm_chain, calm_as_of):
    """Quote noise on one expiry must not read as market panic."""
    term = term_structure_slope(calm_chain, as_of=calm_as_of)
    assert term is not None
    flat = term.model_copy(update={"slope": 0.001})
    assert not flat.is_backwardation and not flat.is_contango
    assert flat.shape == "flat"


# ------------------------------------------------------------------ ranks


def test_percentile_and_range_rank_basics():
    series = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile_of(3.0, series) == pytest.approx(60.0)
    assert percentile_of(5.0, series) == pytest.approx(100.0)
    assert range_rank(3.0, series) == pytest.approx(50.0)
    assert range_rank(1.0, series) == pytest.approx(0.0)
    assert range_rank(5.0, [2.0, 2.0, 2.0]) is None, "degenerate range must not divide by zero"


def test_rv_percentile_is_computable_from_real_bars(real_spy_bars):
    """This one is real: bar history exists over any lookback, so a 252-day
    realized-vol percentile is legitimate and disclosable."""
    ranked = rv_percentile(real_spy_bars.closes, window=20, lookback=252)
    assert ranked.computable
    assert ranked.percentile is not None and 0.0 <= ranked.percentile <= 100.0
    assert ranked.value == pytest.approx(close_to_close_vol(real_spy_bars.closes, 20))
    assert "trading days" in ranked.label


def test_rv_percentile_refuses_on_a_short_series():
    ranked = rv_percentile(np.linspace(100, 110, 40), window=20, lookback=252)
    assert not ranked.computable
    assert ranked.percentile is None


def test_iv_rank_refuses_until_enough_observations_are_collected():
    """Alpaca serves no historical IV. Until the store has accumulated enough,
    the honest answer is 'unavailable', not a number computed from four points."""
    ranked = iv_rank_from_history(0.20, [0.18, 0.19, 0.21], window_days=1)
    assert not ranked.computable
    assert ranked.percentile is None
    assert "Alpaca serves no historical IV" in ranked.label


def test_iv_rank_needs_twenty_distinct_days_before_it_prints():
    """A percentile over a short window is an artefact, not a measurement.

    40 observations crammed into 5 distinct days must NOT produce a rank —
    that is "IV rank 100 over 0 day(s)" wearing a different hat. The same
    series over 25 days ranks normally, window disclosed.
    """
    history = list(np.linspace(0.15, 0.25, 40))
    building = iv_rank_from_history(0.25, history, window_days=5, distinct_days=5)
    assert not building.computable
    assert "building history, 5 day(s) collected" in building.label

    ranked = iv_rank_from_history(0.25, history, window_days=25, distinct_days=25)
    assert ranked.computable
    assert ranked.percentile == pytest.approx(100.0)
    assert ranked.window_days == 25
    assert "25 day(s)" in ranked.label
    assert "not a 52-week rank" in ranked.label


# ------------------------------------------------------------------ VRP


def test_vrp_is_iv_minus_rv():
    assert variance_risk_premium(0.24, 0.10) == pytest.approx(0.14)
    assert variance_risk_premium(0.10, 0.24) == pytest.approx(-0.14)


@pytest.fixture
def cfg() -> Settings:
    return Settings(vrp_sell_floor=4.0, vrp_buy_ceiling=-2.0)


@pytest.fixture
def contango(calm_chain, calm_as_of):
    return term_structure_slope(calm_chain, as_of=calm_as_of)


@pytest.fixture
def backwardation(stressed_chain, calm_as_of):
    return term_structure_slope(stressed_chain, as_of=calm_as_of)


def test_regime_sell_vol_when_premium_is_rich(cfg, contango):
    call = classify_regime(0.14, contango, None, settings=cfg)
    assert call.regime == "SELL_VOL"
    assert "+14.0 points" in call.reason


def test_regime_buy_vol_when_premium_is_cheap(cfg, contango):
    call = classify_regime(-0.05, contango, None, settings=cfg)
    assert call.regime == "BUY_VOL"
    assert "underpriced" in call.reason


def test_regime_abstains_inside_the_band(cfg, contango):
    call = classify_regime(0.01, contango, None, settings=cfg)
    assert call.regime == "ABSTAIN"
    assert "fairly priced" in call.reason


@pytest.mark.parametrize(
    ("vrp_points", "expected"),
    [
        (4.0, "SELL_VOL"),  # exactly on the floor — inclusive
        (3.99, "ABSTAIN"),  # a hair below
        (-2.0, "BUY_VOL"),  # exactly on the ceiling — inclusive
        (-1.99, "ABSTAIN"),
        (0.0, "ABSTAIN"),
    ],
)
def test_regime_boundaries_are_exact(cfg, contango, vrp_points, expected):
    assert classify_regime(vrp_points * VOL_POINT, contango, None, settings=cfg).regime == expected


def test_backwardation_blocks_selling_however_attractive_the_vrp(cfg, backwardation):
    """The hardest rule in the system. Selling volatility into a panic is the
    single most reliable way to blow up an options account — docs/04 §6."""
    call = classify_regime(0.30, backwardation, None, settings=cfg)
    assert call.regime == "ABSTAIN"
    assert "Backwardation" in call.reason
    assert "+30.0 points is not a reason" in call.reason


def test_backwardation_does_not_block_buying_volatility(cfg, backwardation):
    """Inverted curve plus cheap vol is a legitimate reason to *buy* premium.
    The gate is about selling into stress, not about refusing to act at all."""
    assert classify_regime(-0.05, backwardation, None, settings=cfg).regime == "BUY_VOL"


def test_unknown_term_structure_is_not_a_flat_one(cfg):
    call = classify_regime(0.20, None, None, settings=cfg)
    assert call.regime == "ABSTAIN"
    assert "Term structure unavailable" in call.reason


def test_high_realized_vol_percentile_stands_the_desk_down(cfg, contango):
    """Elevated IV when the underlying is already moving violently is about to
    be realized, not collected."""
    from skew.vol.rank import RankedValue

    hot = RankedValue(
        value=0.4,
        percentile=RV_PERCENTILE_CEILING,
        window_days=252,
        observations=252,
        computable=True,
    )
    call = classify_regime(0.20, contango, hot, settings=cfg)
    assert call.regime == "ABSTAIN"
    assert "percentile" in call.reason

    cool = hot.model_copy(update={"percentile": 50.0})
    assert classify_regime(0.20, contango, cool, settings=cfg).regime == "SELL_VOL"


def test_uncomputable_percentile_does_not_block(cfg, contango):
    from skew.vol.rank import RankedValue

    unknown = RankedValue(value=0.4, percentile=99.0, computable=False)
    assert classify_regime(0.20, contango, unknown, settings=cfg).regime == "SELL_VOL"


def test_regime_never_sees_price_direction(cfg, contango):
    """The classifier's signature accepts vol, term structure and a vol
    percentile. There is nowhere to pass a price forecast, and that is the
    product. If a direction argument ever appears here, the thesis is gone."""
    import inspect

    params = set(inspect.signature(classify_regime).parameters)
    assert params == {"vrp", "term", "rv_pct", "settings"}


# ------------------------------------------------------------------ end to end


def test_build_vol_state_end_to_end(real_spy_chain, real_spy_bars, real_as_of):
    state = build_vol_state(real_spy_chain, real_spy_bars, as_of=real_as_of)

    assert state.symbol == "SPY"
    assert state.spot > 0
    assert 0.02 < state.iv_atm < 2.0
    assert 0.0 < state.rv_20 < 2.0
    assert state.vrp == pytest.approx(state.iv_atm - state.rv_20)
    assert state.regime in ("SELL_VOL", "BUY_VOL", "ABSTAIN")
    assert state.note, "every state must carry the sentence explaining it"
    assert len(state.skew_curve) > 5
    assert len(state.term_curve) >= 2
    # No IV history collected yet, so the rank must be None rather than invented.
    assert state.iv_rank is None
    assert state.iv_rank_window_days == 0


def test_build_vol_state_refuses_rather_than_returning_zeros(real_spy_bars):
    """A half-populated VolState would put a zero into the VRP, and a zero VRP
    looks like a real measurement."""
    from skew.data.chains import OptionChain

    with pytest.raises(ValueError, match="No usable ATM implied volatility"):
        build_vol_state(OptionChain(symbol="SPY", spot=769.0), real_spy_bars)


def test_build_vol_state_refuses_on_too_few_bars(real_spy_chain, real_as_of):
    from skew.data.bars import BarSeries

    short = BarSeries(symbol="SPY", bars=real_spy_chain and [])
    with pytest.raises(ValueError, match="Cannot compute realized volatility"):
        build_vol_state(real_spy_chain, short, as_of=real_as_of)


# ------------------------------------------------------------------ chart data


def test_skew_slices_carry_the_front_curve_plus_ghosts(real_spy_chain, real_spy_bars, real_as_of):
    """The front slice is the drawn curve; later expiries ride behind as ghosts."""
    state = build_vol_state(real_spy_chain, real_spy_bars, as_of=real_as_of)
    assert state.skew_slices, "at least the front slice must exist"
    front = state.skew_slices[0]
    assert [p.strike for p in front.points] == [p.strike for p in state.skew_curve]
    dtes = [s.dte for s in state.skew_slices]
    assert dtes == sorted(dtes), "ghosts must be later expiries, in order"
    assert len(state.skew_slices) <= 3
    for s in state.skew_slices:
        assert len(s.points) >= 5


def test_vol_cone_bands_are_ordered_and_honest(real_spy_bars):
    from skew.vol.vrp import CONE_HORIZONS, build_vol_cone

    cone = build_vol_cone(real_spy_bars.closes)
    assert cone, "252 days of bars must support at least the short horizons"
    for point in cone:
        assert point.horizon in CONE_HORIZONS
        assert point.p10 <= point.p25 <= point.p50 <= point.p75 <= point.p90
        assert point.p10 > 0.0 and point.p90 < 2.0
        assert point.current > 0


def test_vol_cone_refuses_horizons_without_enough_history():
    import numpy as np

    from skew.vol.vrp import build_vol_cone

    rng = np.random.default_rng(7)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 45)))
    cone = build_vol_cone(closes)
    horizons = {c.horizon for c in cone}
    assert 90 not in horizons, "a 90d band from 45 closes would be an invention"
