"""The variance risk premium — the one signal this desk trades.

    VRP = implied volatility − trailing realized volatility

Implied volatility is what the market charges for movement. Realized volatility
is how much movement actually happened. The gap between them is persistent and
positive on average because people buy protection and funds hedge, and that
demand pushes IV above what subsequently gets realized. It is a documented
structural feature of options markets, not a pattern found in a backtest.

When VRP is large and positive, options are expensive relative to actual
movement, so selling premium has an edge. When VRP is near zero or negative,
movement is cheap and buying has an edge.

**Notice what is absent: any opinion about direction.** The classifier below
never sees a price forecast, a moving average, or a trend. If you find yourself
adding one, you are working on a different and worse project.

UNITS: volatilities here are annualised decimals (0.241 = 24.1%). The config
thresholds are in vol points because that is how a human reasons about them, and
``VOL_POINT`` is the one conversion.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import numpy as np
from pydantic import BaseModel

from skew.config import Settings
from skew.config import settings as default_settings
from skew.models import ConePoint, Regime, SkewSlice, VolState
from skew.vol.implied import atm_implied_vol, skew_slice
from skew.vol.rank import RankedValue, iv_rank_from_history, rv_percentile
from skew.vol.realized import (
    InsufficientBars,
    close_to_close_vol,
    parkinson_vol,
    rolling_close_to_close,
)
from skew.vol.term import TermStructure, term_structure_slope

if TYPE_CHECKING:  # pragma: no cover
    from skew.data.bars import BarSeries
    from skew.data.chains import OptionChain

# One vol point = one percentage point of annualised volatility.
VOL_POINT = 0.01

# Above this realized-vol percentile the underlying is already moving violently.
# Elevated IV in that state is usually about to be realized rather than
# collected, so we stand down regardless of how attractive VRP looks.
RV_PERCENTILE_CEILING = 90.0


class RegimeCall(BaseModel):
    """The classifier's output, with the sentence that explains it."""

    regime: Regime
    vrp: float
    reason: str


def variance_risk_premium(iv_atm: float, rv_20: float) -> float:
    """IV minus realized. Positive means volatility is rich."""
    return float(iv_atm - rv_20)


def classify_regime(
    vrp: float,
    term: TermStructure | None,
    rv_pct: RankedValue | None = None,
    settings: Settings | None = None,
) -> RegimeCall:
    """Turn the volatility picture into SELL_VOL, BUY_VOL or ABSTAIN.

    The order of these checks is deliberate. Every disqualifying condition is
    evaluated before any opportunity is, so an attractive VRP can never talk the
    system past a structural problem with the market.
    """
    cfg = settings or default_settings
    sell_floor = cfg.vrp_sell_floor * VOL_POINT
    buy_ceiling = cfg.vrp_buy_ceiling * VOL_POINT
    vrp_pts = vrp / VOL_POINT

    # 1. An unknown term structure is not a flat one. Abstain.
    if term is None:
        return RegimeCall(
            regime="ABSTAIN",
            vrp=vrp,
            reason=(
                "Term structure unavailable — fewer than two expiries with usable "
                "quotes. Abstaining rather than trading a curve we cannot see."
            ),
        )

    # 2. Backwardation. The market is pricing near-term stress; selling premium
    #    into it is the standard way to blow up an options account.
    if term.is_backwardation and vrp > 0:
        return RegimeCall(
            regime="ABSTAIN",
            vrp=vrp,
            reason=(
                f"Backwardation — {term.near_dte}d IV {term.near_iv * 100:.1f} above "
                f"{term.far_dte}d IV {term.far_iv * 100:.1f}. The market is pricing "
                f"near-term stress; VRP of {vrp_pts:+.1f} points is not a reason to sell "
                f"volatility into it."
            ),
        )

    # 3. The underlying is already moving at the top of its own range.
    if (
        rv_pct is not None
        and rv_pct.computable
        and (rv_pct.percentile or 0.0) >= (RV_PERCENTILE_CEILING)
    ):
        return RegimeCall(
            regime="ABSTAIN",
            vrp=vrp,
            reason=(
                f"Realized volatility is in the {rv_pct.percentile:.0f}th percentile of "
                f"its own {rv_pct.window_days}-day distribution. Elevated implied vol "
                f"here is about to be realized, not collected."
            ),
        )

    # 4. Volatility is rich.
    if vrp >= sell_floor:
        return RegimeCall(
            regime="SELL_VOL",
            vrp=vrp,
            reason=(
                f"Implied volatility exceeds realized by {vrp_pts:+.1f} points, above the "
                f"{cfg.vrp_sell_floor:.1f}-point entry floor, with the curve in "
                f"{term.shape}. Volatility is rich — sell defined-risk premium."
            ),
        )

    # 5. Volatility is cheap.
    if vrp <= buy_ceiling:
        return RegimeCall(
            regime="BUY_VOL",
            vrp=vrp,
            reason=(
                f"Implied volatility sits {abs(vrp_pts):.1f} points below realized, under "
                f"the {cfg.vrp_buy_ceiling:.1f}-point ceiling. Movement is underpriced — "
                f"buy premium with defined risk."
            ),
        )

    # 6. In between. Not every moment is a trade.
    return RegimeCall(
        regime="ABSTAIN",
        vrp=vrp,
        reason=(
            f"VRP {vrp_pts:+.1f} points sits inside the "
            f"{cfg.vrp_buy_ceiling:.1f} to {cfg.vrp_sell_floor:.1f} band. Volatility is "
            f"fairly priced — no edge, no trade."
        ),
    )


CONE_HORIZONS = (10, 20, 30, 60, 90)


def build_skew_slices(chain, front_expiry, as_of, ghosts: int = 2) -> list[SkewSlice]:
    """The front slice plus up to ``ghosts`` later expiries with usable curves."""
    ref = as_of or chain.as_of.date()
    slices: list[SkewSlice] = []
    expiries = [front_expiry] + [e for e in chain.expiries if e > front_expiry]
    for expiry in expiries:
        if len(slices) > ghosts:
            break
        points = skew_slice(chain, expiry=expiry, as_of=ref)
        if len(points) >= 5:
            slices.append(SkewSlice(expiry=expiry, dte=(expiry - ref).days, points=points))
    return slices


def build_vol_cone(closes: np.ndarray, lookback: int = 252) -> list[ConePoint]:
    """Percentile bands of realized vol per horizon, from the symbol's own bars.

    Each horizon's rolling series is ranked over its trailing ``lookback``
    observations. Horizons without at least 30 observations are omitted rather
    than padded — a band drawn from a handful of points would be an invention.
    """
    cone: list[ConePoint] = []
    for horizon in CONE_HORIZONS:
        series = rolling_close_to_close(np.asarray(closes, dtype=float), window=horizon)
        if series.size < 30:
            continue
        window = series[-lookback:]
        p10, p25, p50, p75, p90 = (float(np.percentile(window, q)) for q in (10, 25, 50, 75, 90))
        cone.append(
            ConePoint(
                horizon=horizon,
                p10=p10,
                p25=p25,
                p50=p50,
                p75=p75,
                p90=p90,
                current=float(series[-1]),
            )
        )
    return cone


def build_vol_state(
    chain: OptionChain,
    bars: BarSeries,
    iv_history: list[float] | None = None,
    iv_history_window_days: int = 0,
    target_dte: int = 30,
    as_of: date | None = None,
    settings: Settings | None = None,
) -> VolState:
    """Assemble the complete volatility picture for one underlying.

    Raises rather than returning a half-populated state: an incomplete VolState
    would silently propagate a zero into the VRP, and a zero VRP looks like a
    real measurement. Callers catch and abstain with the message.
    """
    cfg = settings or default_settings
    ref = as_of or chain.as_of.date()

    atm = atm_implied_vol(chain, target_dte=target_dte, as_of=ref)
    if atm is None or atm.iv <= 0:
        raise ValueError(
            f"No usable ATM implied volatility for {chain.symbol} near {target_dte} DTE. "
            f"Abstaining rather than inventing a number."
        )

    try:
        rv_20 = close_to_close_vol(bars.closes, window=20)
        rv_park = parkinson_vol(bars.highs, bars.lows, window=20)
    except InsufficientBars as exc:
        raise ValueError(f"Cannot compute realized volatility for {chain.symbol}: {exc}") from exc

    vrp = variance_risk_premium(atm.iv, rv_20)
    term = term_structure_slope(chain, as_of=ref)
    rv_pct = rv_percentile(bars.closes, window=20, lookback=252)
    call = classify_regime(vrp, term, rv_pct, settings=cfg)

    iv_rank = iv_rank_from_history(atm.iv, iv_history or [], iv_history_window_days)

    return VolState(
        symbol=chain.symbol,
        spot=chain.spot,
        iv_atm=atm.iv,
        rv_20=rv_20,
        rv_parkinson=rv_park,
        vrp=vrp,
        rv_percentile=rv_pct.percentile if rv_pct.computable else 0.0,
        term_slope=term.slope if term else 0.0,
        regime=call.regime,
        as_of=chain.as_of,
        iv_rank_window_days=iv_history_window_days,
        iv_rank=iv_rank.percentile if iv_rank.computable else None,
        skew_curve=skew_slice(chain, target_dte=target_dte, as_of=ref),
        skew_slices=build_skew_slices(chain, atm.expiry, ref),
        term_curve=term.points if term else [],
        vol_cone=build_vol_cone(bars.closes),
        note=call.reason,
    )
