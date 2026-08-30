"""Percentile and rank measures — and an honest account of what is computable.

Read docs/01-ARCHITECTURE.md §4 before changing anything here.

IV rank is conventionally "where does today's IV sit within its 52-week range".
**Alpaca does not serve historical implied volatility.** There is no endpoint.
A real 252-day IV rank is not computable from this API, and any code that claims
one is lying.

So this module provides three things, in descending order of honesty:

1. :func:`rv_percentile` — realized-vol percentile over a true 252-day lookback.
   Genuinely computable, because bar history *is* available. This is the regime
   filter the system actually uses.
2. :func:`iv_rank_from_history` — IV rank over whatever window
   ``skew/data/store.py`` has accumulated since we started polling, returned
   together with the window length so the number can never be shown without its
   caveat.
3. Nothing else. There is no fabricated 52-week IV rank anywhere in this
   codebase, and adding one would be the fastest way to lose a finance judge.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from skew.data.store import MIN_OBSERVATIONS_FOR_RANK
from skew.vol.realized import rolling_close_to_close

# A percentile needs a distribution. Twenty distinct trading days is the floor
# below which "IV rank" is an artefact of a short window, not a measurement.
MIN_DAYS_FOR_RANK = 20


class RankedValue(BaseModel):
    """A percentile that carries its own provenance.

    ``window_days`` and ``observations`` travel with the value everywhere it
    goes, so the UI can label it truthfully and a five-day window can never be
    mistaken for a year.
    """

    value: float
    percentile: float | None = None
    window_days: int = 0
    observations: int = 0
    computable: bool = False
    label: str = ""


def percentile_of(value: float, series: np.ndarray | list[float]) -> float:
    """Fraction of observations at or below ``value``, as 0–100.

    Plain empirical rank. No interpolation, no distributional assumption — with
    a few hundred noisy observations, a fancier estimator would be false
    precision.
    """
    arr = np.asarray(list(series), dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return 0.0
    return float(np.count_nonzero(arr <= value) / arr.size * 100.0)


def range_rank(value: float, series: np.ndarray | list[float]) -> float | None:
    """Position within the min-max range, as 0–100.

    This is the textbook "IV rank" formula, ``(v − min) / (max − min)``, as
    opposed to the percentile. Returns None on a degenerate range rather than
    dividing by zero.
    """
    arr = np.asarray(list(series), dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 2:
        return None
    lo, hi = float(np.min(arr)), float(np.max(arr))
    if hi - lo <= 1e-12:
        return None
    return float(np.clip((value - lo) / (hi - lo), 0.0, 1.0) * 100.0)


def rv_percentile(
    closes: np.ndarray,
    window: int = 20,
    lookback: int = 252,
) -> RankedValue:
    """Today's realized volatility within its own trailing distribution.

    This one is real. Bar history is available over any lookback, so a 252-day
    realized-vol percentile is a legitimate, disclosable regime measure — and it
    is the substitute for IV rank that docs/01-ARCHITECTURE.md §4 calls option C.

    A high reading means the underlying has been moving a lot lately relative to
    its own history, which is when implied vol tends to be elevated for reasons
    that are about to be realized rather than about to be collected.
    """
    series = rolling_close_to_close(np.asarray(closes, dtype=float), window)
    if series.size == 0:
        return RankedValue(
            value=0.0,
            computable=False,
            label=f"realized-vol percentile needs {window + 1}+ closes",
        )

    recent = series[-lookback:]
    current = float(series[-1])
    if recent.size < 30:
        return RankedValue(
            value=current,
            window_days=int(recent.size),
            observations=int(recent.size),
            computable=False,
            label=f"only {recent.size} observations — percentile not meaningful yet",
        )

    return RankedValue(
        value=current,
        percentile=percentile_of(current, recent),
        window_days=int(recent.size),
        observations=int(recent.size),
        computable=True,
        label=f"realized-vol percentile over {recent.size} trading days",
    )


def iv_rank_from_history(
    current_iv: float,
    history: list[float],
    window_days: int,
    distinct_days: int | None = None,
) -> RankedValue:
    """IV rank over the window we have actually accumulated.

    ``window_days`` is not decoration — it is the disclosure. Callers must
    render it next to the number.

    Two gates, both required. Observations: a distribution needs members.
    Distinct DAYS: the poller writes many rows a day, so an observation count
    alone lets "IV rank 100 over 0 days" through — 52 rows from one afternoon
    are one data point wearing 52 hats. Below ``MIN_DAYS_FOR_RANK`` distinct
    days, no rank is printed at all.
    """
    clean = [v for v in history if v is not None and np.isfinite(v) and v > 0]
    days = distinct_days if distinct_days is not None else window_days
    if days < MIN_DAYS_FOR_RANK:
        return RankedValue(
            value=current_iv,
            window_days=days,
            observations=len(clean),
            computable=False,
            label=(
                f"IV rank unavailable — building history, {days} day(s) collected of "
                f"the {MIN_DAYS_FOR_RANK} needed. Alpaca serves no historical IV, so "
                f"this history is built forward from first run."
            ),
        )
    if len(clean) < MIN_OBSERVATIONS_FOR_RANK:
        return RankedValue(
            value=current_iv,
            window_days=days,
            observations=len(clean),
            computable=False,
            label=(
                f"IV rank unavailable — {len(clean)} observations collected, "
                f"{MIN_OBSERVATIONS_FOR_RANK} needed. Alpaca serves no historical IV, "
                f"so this history is built forward from first run."
            ),
        )

    rank = range_rank(current_iv, clean)
    if rank is None:
        return RankedValue(
            value=current_iv,
            window_days=window_days,
            observations=len(clean),
            computable=False,
            label="IV rank unavailable — no dispersion in the collected window yet",
        )

    return RankedValue(
        value=current_iv,
        percentile=rank,
        window_days=window_days,
        observations=len(clean),
        computable=True,
        label=(
            f"IV rank over {window_days} day(s) of self-collected history "
            f"({len(clean)} observations) — not a 52-week rank; Alpaca serves no "
            f"historical IV"
        ),
    )
