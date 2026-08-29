"""Capture real Alpaca responses to tests/fixtures/.

docs/PHASE-01: "Save one real chain response and one real bars response to
tests/fixtures/ as JSON. All unit tests run off these — no network in tests."

This writes the **raw REST shape**, not the SDK objects, so the fixtures
reconstruct through ``OptionsSnapshot(symbol, raw_data)`` and every parser is
exercised against the schema Alpaca actually serves. Contracts with no implied
volatility or no bid are kept deliberately: the tradeability filter has to be
tested against the real proportion of junk in a live chain, not a cleaned-up
version of one.

    python -m scripts.capture_fixtures

Run it again whenever the shape of the API changes. It never captures anything
account-specific — no positions, no orders, no account numbers — so the output
is safe to commit.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from skew.data.broker import Broker

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

# Wide enough to contain every structure we build, narrow enough to keep the
# fixture reviewable in a diff.
DTE_MAX = 60
STRIKE_WINDOW = 0.12


def _iso(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _quote_raw(quote: Any) -> dict[str, Any] | None:
    if quote is None:
        return None
    return {
        "t": _iso(getattr(quote, "timestamp", None)),
        "bp": getattr(quote, "bid_price", None),
        "bs": getattr(quote, "bid_size", None),
        "bx": getattr(quote, "bid_exchange", None),
        "ap": getattr(quote, "ask_price", None),
        "as": getattr(quote, "ask_size", None),
        "ax": getattr(quote, "ask_exchange", None),
        "c": getattr(quote, "conditions", None),
        "z": getattr(quote, "tape", None),
    }


def _trade_raw(trade: Any) -> dict[str, Any] | None:
    if trade is None:
        return None
    return {
        "t": _iso(getattr(trade, "timestamp", None)),
        "p": getattr(trade, "price", None),
        "s": getattr(trade, "size", None),
        "x": getattr(trade, "exchange", None),
        "i": getattr(trade, "id", None),
        "c": getattr(trade, "conditions", None),
        "z": getattr(trade, "tape", None),
    }


def _greeks_raw(greeks: Any) -> dict[str, Any] | None:
    if greeks is None:
        return None
    return {k: getattr(greeks, k, None) for k in ("delta", "gamma", "rho", "theta", "vega")}


def capture_chain(broker: Broker, symbol: str) -> dict[str, Any]:
    spot = broker.fetch_spot(symbol)
    if spot <= 0:
        raise RuntimeError(f"No usable spot for {symbol}; refusing to capture a fixture.")

    today = datetime.now(UTC).date()
    snapshots = broker.fetch_option_chain(
        symbol,
        expiry_gte=today,
        expiry_lte=today + timedelta(days=DTE_MAX),
        strike_gte=spot * (1 - STRIKE_WINDOW),
        strike_lte=spot * (1 + STRIKE_WINDOW),
    )

    raw: dict[str, Any] = {}
    for contract_symbol, snap in snapshots.items():
        entry: dict[str, Any] = {}
        if (q := _quote_raw(getattr(snap, "latest_quote", None))) is not None:
            entry["latestQuote"] = q
        if (t := _trade_raw(getattr(snap, "latest_trade", None))) is not None:
            entry["latestTrade"] = t
        if (iv := getattr(snap, "implied_volatility", None)) is not None:
            entry["impliedVolatility"] = iv
        if (g := _greeks_raw(getattr(snap, "greeks", None))) is not None:
            entry["greeks"] = g
        raw[contract_symbol] = entry

    expiries = sorted({s[-15:-9] for s in raw})
    oi = broker.fetch_open_interest(symbol, expiries=[today, today + timedelta(days=DTE_MAX)])

    with_iv = sum(1 for e in raw.values() if e.get("impliedVolatility"))
    return {
        "_note": (
            "REAL captured Alpaca response. Raw REST shape, so "
            "OptionsSnapshot(symbol, raw_data) reconstructs it. Contains no "
            "account-identifying data. Regenerate with: python -m scripts.capture_fixtures"
        ),
        "_captured_at": datetime.now(UTC).isoformat(),
        "_stats": {
            "contracts": len(raw),
            "with_implied_vol": with_iv,
            "without_implied_vol": len(raw) - with_iv,
            "expiry_codes": expiries[:12],
            "open_interest_entries": len(oi),
        },
        "underlying": symbol,
        "spot": spot,
        "as_of": datetime.now(UTC).isoformat(),
        "snapshots": raw,
        "open_interest": {k: v for k, v in oi.items() if k in raw},
    }


def capture_bars(broker: Broker, symbol: str) -> dict[str, Any]:
    rows = broker.fetch_daily_bars(symbol, lookback_days=380)
    if len(rows) < 60:
        raise RuntimeError(f"Only {len(rows)} bars for {symbol}; refusing to capture a fixture.")
    return {
        "_note": "REAL captured Alpaca daily bars. Regenerate with scripts/capture_fixtures.py",
        "_captured_at": datetime.now(UTC).isoformat(),
        "symbol": symbol,
        "bars": [{**r, "date": _iso(r["date"])} for r in rows],
    }


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    broker = Broker()

    for symbol, chain_name, bars_name in (
        ("SPY", "chain_spy_real.json", "bars_spy_real.json"),
        ("NVDA", "chain_nvda_real.json", "bars_nvda_real.json"),
    ):
        chain = capture_chain(broker, symbol)
        (FIXTURES / chain_name).write_text(json.dumps(chain, indent=1, default=str))
        stats = chain["_stats"]
        print(
            f"{chain_name}: spot {chain['spot']}, {stats['contracts']} contracts "
            f"({stats['with_implied_vol']} with IV), {stats['open_interest_entries']} OI"
        )

        bars = capture_bars(broker, symbol)
        (FIXTURES / bars_name).write_text(json.dumps(bars, indent=1, default=str))
        print(f"{bars_name}: {len(bars['bars'])} bars, last {bars['bars'][-1]['date']}")


if __name__ == "__main__":
    main()
