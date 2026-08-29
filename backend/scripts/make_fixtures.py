"""Generate test fixtures in Alpaca's exact raw JSON shape.

WHY THESE ARE SYNTHETIC
-----------------------
docs/PHASE-01 asks for one real captured chain response and one real bars
response in ``tests/fixtures/``. That capture needs live API credentials, which
are not present in this environment, so these fixtures are generated instead —
in the **exact raw REST shape** Alpaca returns, so that
``OptionsSnapshot(symbol, raw_data)`` reconstructs them and every parser is
exercised on the real schema rather than a convenient one.

Replace them with real captures the moment credentials exist:

    python -m scripts.capture_fixtures        # see the sibling script

The surface here is priced with an independent Black-Scholes implementation,
deliberately separate from ``skew/stress/reprice.py``. Two independent
implementations that agree is a much stronger check than one implementation
agreeing with itself.

Fixtures produced:

* ``chain_spy.json``      — calm market, contango, normal put skew
* ``chain_stressed.json`` — panic, **backwardation**, steep skew. Exercises the
  gate that must never let a premium sale through.
* ``bars_spy.json``       — 400 daily bars from a seeded generator
* ``bars_known.json``     — a hand-built series with a hand-computed volatility
"""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

# Anchored so fixtures are reproducible and DTEs are stable across runs.
AS_OF = datetime(2026, 8, 28, 20, 0, tzinfo=UTC)
RISK_FREE = 0.042


# ----------------------------------------------------------------------
# Independent Black-Scholes (cross-check for skew/stress/reprice.py)
# ----------------------------------------------------------------------


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_price_and_greeks(
    spot: float, strike: float, years: float, vol: float, right: str, rate: float = RISK_FREE
) -> dict[str, float]:
    """Price and Greeks. Greeks in the same per-contract units Alpaca reports:
    delta per $1, theta per calendar day, vega per 1 IV point."""
    if years <= 0 or vol <= 0:
        intrinsic = max(0.0, spot - strike) if right == "CALL" else max(0.0, strike - spot)
        return {
            "price": intrinsic,
            "delta": 0.0,
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
            "rho": 0.0,
        }

    sqrt_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    disc = math.exp(-rate * years)

    if right == "CALL":
        price = spot * _norm_cdf(d1) - strike * disc * _norm_cdf(d2)
        delta = _norm_cdf(d1)
        theta_yr = -(spot * _norm_pdf(d1) * vol) / (2 * sqrt_t) - rate * strike * disc * _norm_cdf(
            d2
        )
        rho = strike * years * disc * _norm_cdf(d2) / 100.0
    else:
        price = strike * disc * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
        theta_yr = -(spot * _norm_pdf(d1) * vol) / (2 * sqrt_t) + rate * strike * disc * _norm_cdf(
            -d2
        )
        rho = -strike * years * disc * _norm_cdf(-d2) / 100.0

    return {
        "price": price,
        "delta": delta,
        "gamma": _norm_pdf(d1) / (spot * vol * sqrt_t),
        "theta": theta_yr / 365.0,
        "vega": spot * _norm_pdf(d1) * sqrt_t / 100.0,
        "rho": rho,
    }


# ----------------------------------------------------------------------
# Vol surface
# ----------------------------------------------------------------------


def surface_iv(
    strike: float,
    spot: float,
    dte: int,
    atm_30d: float,
    term_slope_per_year: float,
    skew: float,
    smile: float,
) -> float:
    """A plausible equity surface: ATM level by tenor, plus a put-skewed smile."""
    tenor_adj = term_slope_per_year * (dte - 30) / 365.0
    atm = max(0.03, atm_30d + tenor_adj)
    m = math.log(strike / spot)
    return max(0.02, atm - skew * m + smile * m * m)


def _quote(price: float, spread_pct: float, ts: str) -> tuple[float, float]:
    """Bid/ask around theoretical, rounded to the penny like a real quote."""
    half = max(0.01, price * spread_pct / 2.0)
    bid = max(0.01, round(price - half, 2))
    ask = round(max(bid + 0.01, price + half), 2)
    return bid, ask


def build_chain_fixture(
    underlying: str,
    spot: float,
    atm_30d: float,
    term_slope_per_year: float,
    skew: float,
    smile: float,
    expiries: list[date],
    strike_step: float,
    strike_span_pct: float = 0.18,
    spread_pct: float = 0.04,
    base_oi: int = 4000,
) -> dict:
    ts = AS_OF.isoformat().replace("+00:00", "Z")
    snapshots: dict[str, dict] = {}
    open_interest: dict[str, int] = {}

    lo = math.floor(spot * (1 - strike_span_pct) / strike_step) * strike_step
    hi = math.ceil(spot * (1 + strike_span_pct) / strike_step) * strike_step

    for expiry in expiries:
        dte = (expiry - AS_OF.date()).days
        years = dte / 365.0
        strike = lo
        while strike <= hi + 1e-9:
            for right in ("CALL", "PUT"):
                iv = surface_iv(strike, spot, dte, atm_30d, term_slope_per_year, skew, smile)
                greeks = bs_price_and_greeks(spot, strike, years, iv, right)
                price = greeks["price"]
                if price < 0.02:
                    strike_sym = f"{round(strike * 1000):08d}"
                    sym = f"{underlying}{expiry:%y%m%d}{right[0]}{strike_sym}"
                    # Deep OTM contracts that would not have a real two-sided
                    # market: present in the chain, but with no bid. The
                    # tradeability filter must skip them.
                    snapshots[sym] = {
                        "latestQuote": {
                            "t": ts,
                            "bp": 0.0,
                            "bs": 0,
                            "ap": 0.05,
                            "as": 0,
                            "bx": "W",
                            "ax": "W",
                            "c": [" "],
                            "z": "C",
                        },
                        "impliedVolatility": round(iv, 4),
                        "greeks": {
                            k: round(greeks[k], 6)
                            for k in ("delta", "gamma", "rho", "theta", "vega")
                        },
                    }
                    open_interest[sym] = 0
                    continue

                # Wider markets away from the money, like a real book.
                distance = abs(math.log(strike / spot))
                width = spread_pct * (1 + 6 * distance)
                bid, ask = _quote(price, width, ts)
                strike_sym = f"{round(strike * 1000):08d}"
                sym = f"{underlying}{expiry:%y%m%d}{right[0]}{strike_sym}"

                snapshots[sym] = {
                    "latestQuote": {
                        "t": ts,
                        "bp": bid,
                        "bs": 25,
                        "ap": ask,
                        "as": 31,
                        "bx": "W",
                        "ax": "W",
                        "c": [" "],
                        "z": "C",
                    },
                    "latestTrade": {
                        "t": ts,
                        "p": round((bid + ask) / 2, 2),
                        "s": 3,
                        "x": "W",
                        "i": 1,
                        "c": [" "],
                        "z": "C",
                    },
                    "impliedVolatility": round(iv, 4),
                    "greeks": {
                        k: round(greeks[k], 6) for k in ("delta", "gamma", "rho", "theta", "vega")
                    },
                }
                # Open interest concentrates at round strikes near the money.
                nearness = math.exp(-(((strike - spot) / (spot * 0.06)) ** 2))
                roundness = 2.0 if abs(strike % 25) < 1e-9 else 1.0
                open_interest[sym] = int(base_oi * nearness * roundness) + 25
            strike += strike_step

    return {
        "_note": (
            "SYNTHETIC fixture in Alpaca's raw REST shape. Generated by "
            "scripts/make_fixtures.py because no live credentials were available to "
            "capture a real response. Replace with a real capture via "
            "scripts/capture_fixtures.py once keys exist."
        ),
        "underlying": underlying,
        "spot": spot,
        "as_of": AS_OF.isoformat(),
        "snapshots": snapshots,
        "open_interest": open_interest,
    }


# ----------------------------------------------------------------------
# Bars
# ----------------------------------------------------------------------


def build_bars_fixture(
    symbol: str, n: int, start_price: float, annual_vol: float, seed: int
) -> dict:
    """A seeded geometric random walk with realistic intraday ranges."""
    rng = np.random.default_rng(seed)
    daily_sigma = annual_vol / math.sqrt(252)
    returns = rng.normal(0.0002, daily_sigma, n)

    closes = start_price * np.exp(np.cumsum(returns))
    bars = []
    day = AS_OF.date() - timedelta(days=int(n * 1.45))
    prev_close = start_price

    for close in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        open_ = prev_close * (1 + rng.normal(0, daily_sigma * 0.25))
        # Range wide enough that Parkinson exceeds close-to-close, as it does in
        # real data — that difference is the point of having both estimators.
        wick = abs(rng.normal(0, daily_sigma * 0.85)) * close
        high = max(open_, close) + wick
        low = min(open_, close) - abs(rng.normal(0, daily_sigma * 0.85)) * close
        bars.append(
            {
                "date": day.isoformat(),
                "open": round(float(open_), 2),
                "high": round(float(high), 2),
                "low": round(float(max(low, 0.05)), 2),
                "close": round(float(close), 2),
                "volume": int(abs(rng.normal(7.5e7, 1.5e7))),
            }
        )
        prev_close = close
        day += timedelta(days=1)

    return {
        "_note": "SYNTHETIC. See scripts/make_fixtures.py.",
        "symbol": symbol,
        "annual_vol_used": annual_vol,
        "bars": bars,
    }


def build_known_bars() -> dict:
    """A tiny series whose realized volatility is computed by hand in the test.

    Eleven closes, each exactly 1% up or down in log terms, alternating. Ten log
    returns of magnitude 0.01 with alternating sign gives a sample standard
    deviation that can be worked out on paper — see tests/test_vol_realized.py.
    """
    closes = [100.0]
    for i in range(10):
        closes.append(closes[-1] * math.exp(0.01 if i % 2 == 0 else -0.01))

    day = date(2026, 1, 2)
    bars = []
    for close in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        bars.append(
            {
                "date": day.isoformat(),
                # Full precision, deliberately: tests/test_vol_realized.py checks
                # this series against a hand-computed answer to 1e-9, and penny
                # rounding would put a 5e-8 error in the way of that.
                "open": close,
                "high": close * 1.01,
                "low": close / 1.01,
                "close": close,
                "volume": 1_000_000,
            }
        )
        day += timedelta(days=1)

    return {
        "_note": "Hand-constructed series with a hand-computable volatility.",
        "symbol": "TEST",
        "bars": bars,
    }


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    today = AS_OF.date()

    # Weekly and monthly expiries out to ~120 days, like a real SPY board.
    calm_expiries = [today + timedelta(days=d) for d in (2, 9, 16, 23, 30, 37, 51, 79, 114)]

    calm = build_chain_fixture(
        underlying="SPY",
        spot=769.28,
        atm_30d=0.158,
        term_slope_per_year=0.045,  # contango
        skew=0.55,
        smile=1.8,
        expiries=calm_expiries,
        strike_step=5.0,
    )
    (FIXTURES / "chain_spy.json").write_text(json.dumps(calm, indent=1))

    stressed = build_chain_fixture(
        underlying="SPY",
        spot=724.50,
        atm_30d=0.412,
        term_slope_per_year=-0.240,  # backwardation — the market is scared now
        skew=1.35,
        smile=3.4,
        expiries=calm_expiries,
        strike_step=5.0,
        spread_pct=0.10,
        base_oi=2200,
    )
    (FIXTURES / "chain_stressed.json").write_text(json.dumps(stressed, indent=1))

    (FIXTURES / "bars_spy.json").write_text(
        json.dumps(build_bars_fixture("SPY", 400, 660.0, 0.112, seed=20260829), indent=1)
    )
    (FIXTURES / "bars_known.json").write_text(json.dumps(build_known_bars(), indent=1))

    for name in ("chain_spy", "chain_stressed", "bars_spy", "bars_known"):
        path = FIXTURES / f"{name}.json"
        print(f"wrote {path.relative_to(FIXTURES.parents[1])}  ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
