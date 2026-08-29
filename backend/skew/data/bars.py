"""Underlying daily OHLCV.

Realized volatility is computed from these bars, so the series shape matters:
oldest first, no gaps introduced by us, and a hard refusal when there are too
few bars to compute the requested window. Silently returning a volatility from
eleven bars when twenty were asked for is exactly the kind of quiet wrongness
that makes the whole signal untrustworthy.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

# 252 trading days of history for the realized-vol percentile, plus headroom.
DEFAULT_LOOKBACK_DAYS = 380
BARS_CACHE_TTL_SECONDS = 900  # daily bars; no point refetching every loop


class PriceBar(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class BarSeries(BaseModel):
    """A daily bar series for one underlying, oldest first."""

    symbol: str
    bars: list[PriceBar] = Field(default_factory=list)

    def __len__(self) -> int:
        return len(self.bars)

    @property
    def closes(self) -> np.ndarray:
        return np.array([b.close for b in self.bars], dtype=float)

    @property
    def highs(self) -> np.ndarray:
        return np.array([b.high for b in self.bars], dtype=float)

    @property
    def lows(self) -> np.ndarray:
        return np.array([b.low for b in self.bars], dtype=float)

    @property
    def opens(self) -> np.ndarray:
        return np.array([b.open for b in self.bars], dtype=float)

    @property
    def last_close(self) -> float:
        return self.bars[-1].close if self.bars else 0.0

    def tail(self, n: int) -> BarSeries:
        return BarSeries(symbol=self.symbol, bars=self.bars[-n:] if n > 0 else [])


def parse_bars(symbol: str, rows: list[dict[str, Any]]) -> BarSeries:
    """Build a :class:`BarSeries` from raw broker rows. Pure; no network.

    Drops any bar with a non-positive close or an inconsistent high/low, because
    a bad bar poisons every volatility estimate downstream. Sorts ascending so
    callers never have to care what order the API returned.
    """
    bars: list[PriceBar] = []
    for row in rows:
        close = float(row.get("close", 0.0) or 0.0)
        high = float(row.get("high", 0.0) or 0.0)
        low = float(row.get("low", 0.0) or 0.0)
        if close <= 0 or high <= 0 or low <= 0 or high < low:
            continue
        raw_date = row.get("date")
        bar_date = (
            raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date)[:10])
        )
        bars.append(
            PriceBar(
                date=bar_date,
                open=float(row.get("open", close) or close),
                high=high,
                low=low,
                close=close,
                volume=float(row.get("volume", 0.0) or 0.0),
            )
        )

    bars.sort(key=lambda b: b.date)
    # De-duplicate on date, keeping the last observation for a given day.
    deduped: dict[date, PriceBar] = {b.date: b for b in bars}
    return BarSeries(symbol=symbol.upper(), bars=[deduped[d] for d in sorted(deduped)])


class BarClient:
    """Fetches and caches daily bars."""

    def __init__(self, broker: Any) -> None:
        self._broker = broker
        self._cache: dict[str, tuple[float, BarSeries]] = {}

    def invalidate(self, symbol: str | None = None) -> None:
        if symbol is None:
            self._cache.clear()
        else:
            self._cache.pop(symbol.upper(), None)

    def get_bars(
        self,
        symbol: str,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        use_cache: bool = True,
    ) -> BarSeries:
        key = symbol.upper()
        if use_cache:
            hit = self._cache.get(key)
            if hit and (time.monotonic() - hit[0]) < BARS_CACHE_TTL_SECONDS:
                return hit[1]

        series = parse_bars(key, self._broker.fetch_daily_bars(key, lookback_days=lookback_days))
        if len(series) < 25:
            raise ValueError(
                f"Only {len(series)} daily bars for {key}; need at least 25 to compute a "
                f"20-day realized volatility. Abstaining rather than guessing."
            )
        self._cache[key] = (time.monotonic(), series)
        return series
