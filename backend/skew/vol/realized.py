"""Realized volatility estimators.

UNITS — read this once and the rest of the codebase makes sense.

Every volatility number in the Python layer is an **annualised decimal**: 0.241
means 24.1%. That matches what Alpaca returns for implied volatility and what
Black-Scholes expects for sigma, so the maths path contains no conversions and
therefore no conversion bugs. Config thresholds are expressed in *vol points*
(4.0 = four percentage points) because that is how a human thinks about them,
and they are converted in exactly one place — ``skew.vol.vrp.VOL_POINT``. The
frontend multiplies by 100 for display.

ANNUALISATION — √252, not √365. Volatility scales with the square root of the
number of *trading* periods, and there are 252 of them in a year. Using 365
overstates every estimate by about 20%, which would make the variance risk
premium look larger than it is, in our favour. That is the single most
consequential off-by-one in this project.
"""

from __future__ import annotations

from typing import Literal

import numpy as np

TRADING_DAYS = 252
ANNUALISATION = float(np.sqrt(TRADING_DAYS))

Method = Literal["close_to_close", "parkinson", "garman_klass"]

_LN2 = float(np.log(2.0))


class InsufficientBars(ValueError):
    """Not enough observations for the requested window.

    Raised rather than quietly returning a volatility computed from a shorter
    window. A number that silently means something other than what it claims is
    worse than no number.
    """


def log_returns(closes: np.ndarray) -> np.ndarray:
    """Close-to-close log returns. Length n-1 for n closes."""
    closes = np.asarray(closes, dtype=float)
    if closes.size < 2:
        return np.array([], dtype=float)
    if np.any(closes <= 0):
        raise ValueError("Close prices must be positive to take log returns.")
    return np.diff(np.log(closes))


def close_to_close_vol(closes: np.ndarray, window: int = 20) -> float:
    """Annualised close-to-close realized volatility.

    Sample standard deviation of daily log returns over the trailing ``window``
    returns, scaled by √252. ``ddof=1`` because we are estimating the volatility
    of a population from a sample, not describing the sample itself.
    """
    closes = np.asarray(closes, dtype=float)
    if window < 2:
        raise ValueError("window must be at least 2")
    if closes.size < window + 1:
        raise InsufficientBars(
            f"close-to-close vol over a {window}-day window needs {window + 1} closes; "
            f"got {closes.size}."
        )
    returns = log_returns(closes[-(window + 1) :])
    return float(np.std(returns, ddof=1) * ANNUALISATION)


def parkinson_vol(highs: np.ndarray, lows: np.ndarray, window: int = 20) -> float:
    """Annualised Parkinson volatility, from the daily high-low range.

        sigma = sqrt( 1/(4 n ln2) * Σ ln(H/L)² ) * √252

    Close-to-close underestimates when there is intraday range without net
    movement — a day that travels 2% and closes flat registers as zero
    volatility. Parkinson sees that day, which makes it the better input to the
    variance risk premium.
    """
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    if highs.size != lows.size:
        raise ValueError("highs and lows must be the same length")
    if window < 1:
        raise ValueError("window must be at least 1")
    if highs.size < window:
        raise InsufficientBars(
            f"Parkinson vol over a {window}-day window needs {window} bars; got {highs.size}."
        )

    h = highs[-window:]
    ll = lows[-window:]
    if np.any(h <= 0) or np.any(ll <= 0):
        raise ValueError("High and low prices must be positive.")

    log_hl = np.log(h / ll)
    variance = np.sum(log_hl**2) / (4.0 * window * _LN2)
    return float(np.sqrt(max(variance, 0.0)) * ANNUALISATION)


def garman_klass_vol(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    window: int = 20,
) -> float:
    """Annualised Garman-Klass volatility.

        sigma = sqrt( 1/n * Σ [ 0.5 ln(H/L)² − (2ln2 − 1) ln(C/O)² ] ) * √252

    Uses the full OHLC bar and is the most efficient of the three when the
    underlying has no overnight gaps. It can go negative under the square root
    on a pathological bar, so the variance is floored at zero.
    """
    opens, highs = np.asarray(opens, dtype=float), np.asarray(highs, dtype=float)
    lows, closes = np.asarray(lows, dtype=float), np.asarray(closes, dtype=float)
    if not (opens.size == highs.size == lows.size == closes.size):
        raise ValueError("OHLC arrays must be the same length")
    if window < 1:
        raise ValueError("window must be at least 1")
    if opens.size < window:
        raise InsufficientBars(
            f"Garman-Klass vol over a {window}-day window needs {window} bars; got {opens.size}."
        )

    o, h = opens[-window:], highs[-window:]
    ll, c = lows[-window:], closes[-window:]
    if np.any(o <= 0) or np.any(h <= 0) or np.any(ll <= 0) or np.any(c <= 0):
        raise ValueError("OHLC prices must be positive.")

    term_hl = 0.5 * np.log(h / ll) ** 2
    term_co = (2.0 * _LN2 - 1.0) * np.log(c / o) ** 2
    variance = float(np.mean(term_hl - term_co))
    return float(np.sqrt(max(variance, 0.0)) * ANNUALISATION)


def realized_vol(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    window: int = 20,
    method: Method = "close_to_close",
) -> float:
    """Dispatch to one estimator. Keeps callers from repeating the branch."""
    if method == "close_to_close":
        return close_to_close_vol(closes, window)
    if method == "parkinson":
        return parkinson_vol(highs, lows, window)
    if method == "garman_klass":
        return garman_klass_vol(opens, highs, lows, closes, window)
    raise ValueError(f"Unknown realized volatility method: {method!r}")


def rolling_close_to_close(closes: np.ndarray, window: int = 20) -> np.ndarray:
    """The full trailing series of close-to-close vols.

    Feeds the realized-vol percentile in ``rank.py``, which is the one regime
    measure we can honestly compute over 252 days.
    """
    closes = np.asarray(closes, dtype=float)
    if closes.size < window + 1:
        return np.array([], dtype=float)

    returns = log_returns(closes)
    n = returns.size - window + 1
    if n <= 0:
        return np.array([], dtype=float)

    # Strided view: every contiguous `window`-length slice of the return series.
    windows = np.lib.stride_tricks.sliding_window_view(returns, window)
    return np.std(windows, axis=1, ddof=1) * ANNUALISATION


def vol_of_vol(closes: np.ndarray, window: int = 20, lookback: int = 60) -> float:
    """Standard deviation of the rolling realized vol. Context, not a signal."""
    series = rolling_close_to_close(closes, window)
    if series.size < 5:
        return 0.0
    return float(np.std(series[-lookback:], ddof=1))


def sigma_for_horizon(annual_vol: float, days: int) -> float:
    """Scale an annualised vol to a one-standard-deviation move over ``days``.

    Used by the stress engine to size its price shocks: a −2σ shock means two of
    these. Calendar days are converted to trading days at 252/365.
    """
    if annual_vol <= 0 or days <= 0:
        return 0.0
    trading_days = days * (TRADING_DAYS / 365.0)
    return float(annual_vol * np.sqrt(trading_days / TRADING_DAYS))
