"""Chain parsing, against real captured Alpaca responses.

The fixtures here are genuine API captures, junk included. A live SPY chain has
several hundred contracts with no implied volatility and no bid at all, and the
tradeability filter has to survive that — a parser tested only on clean data is
a parser that breaks on day one.
"""

from __future__ import annotations

from datetime import date

import pytest

from skew.data.chains import (
    ContractQuote,
    build_chain,
    build_occ_symbol,
    contract_from_snapshot,
    parse_occ_symbol,
)

# ---------------------------------------------------------------- OCC symbols


def test_parse_occ_symbol_from_the_primer():
    """The worked example in docs/04-OPTIONS-PRIMER.md §2."""
    root, expiry, right, strike = parse_occ_symbol("SPY250919P00580000")
    assert root == "SPY"
    assert expiry == date(2025, 9, 19)
    assert right == "PUT"
    assert strike == 580.0


@pytest.mark.parametrize(
    ("symbol", "root", "expiry", "right", "strike"),
    [
        ("SPY260918C00770000", "SPY", date(2026, 9, 18), "CALL", 770.0),
        ("NVDA261016P00217500", "NVDA", date(2026, 10, 16), "PUT", 217.5),
        # Five-character root, and a sub-dollar strike.
        ("GOOGL260320C00002500", "GOOGL", date(2026, 3, 20), "CALL", 2.5),
        # Space padding is legal under the OCC spec even though Alpaca omits it.
        ("SPY   250919P00580000", "SPY", date(2025, 9, 19), "PUT", 580.0),
    ],
)
def test_parse_occ_symbol_variants(symbol, root, expiry, right, strike):
    assert parse_occ_symbol(symbol) == (root, expiry, right, strike)


@pytest.mark.parametrize(
    "bad",
    [
        "SPY",  # too short
        "SPY250919X00580000",  # not a call or a put
        "250919P00580000",  # no underlying root
        "SPYABCDEFP00580000",  # non-numeric date
        "SPY250919P0058000X",  # non-numeric strike
    ],
)
def test_parse_occ_symbol_rejects_junk(bad):
    with pytest.raises(ValueError):
        parse_occ_symbol(bad)


def test_occ_symbol_round_trips():
    for underlying, expiry, right, strike in [
        ("SPY", date(2026, 9, 18), "CALL", 770.0),
        ("NVDA", date(2026, 10, 16), "PUT", 217.5),
        ("AMD", date(2026, 12, 18), "CALL", 187.5),
    ]:
        sym = build_occ_symbol(underlying, expiry, right, strike)
        assert parse_occ_symbol(sym) == (underlying, expiry, right, strike)


def test_unparseable_contract_is_skipped_not_raised():
    """One malformed key must not take down a whole chain fetch."""
    assert contract_from_snapshot("NOT_AN_OPTION", object()) is None


# ---------------------------------------------------------------- real chains


def test_real_chain_parses(real_spy_chain):
    chain = real_spy_chain
    assert chain.symbol == "SPY"
    assert chain.spot > 0
    assert len(chain.contracts) > 500
    assert len(chain.expiries) >= 3
    assert chain.expiries == sorted(chain.expiries)


def test_iv_and_greeks_come_from_alpaca_not_from_us(real_spy_chain):
    """docs/01-ARCHITECTURE.md §3: they arrive on the snapshot. We never invert."""
    priced = [c for c in real_spy_chain.contracts if c.iv > 0]
    assert len(priced) > 300

    with_greeks = [c for c in priced if c.delta != 0.0]
    assert len(with_greeks) > 300

    for c in with_greeks[:200]:
        assert 0.0 < c.iv < 5.0, f"{c.symbol} IV {c.iv} — decimals, not percent"
        assert -1.01 <= c.delta <= 1.01
        assert c.gamma >= 0.0
        assert c.vega >= 0.0


def test_call_and_put_delta_signs(real_spy_chain):
    """Calls have positive delta, puts negative. A sign flip here inverts strike
    selection, which is how a bull spread quietly becomes a bear spread."""
    for c in real_spy_chain.contracts:
        if c.iv <= 0 or c.delta == 0.0:
            continue
        if c.right == "CALL":
            assert c.delta > 0, f"{c.symbol} call with delta {c.delta}"
        else:
            assert c.delta < 0, f"{c.symbol} put with delta {c.delta}"


def test_real_chain_contains_junk_and_the_filter_removes_it(real_spy_chain):
    """A real chain is full of contracts with no IV or no bid. That is the point."""
    total = len(real_spy_chain.contracts)
    tradeable = real_spy_chain.tradeable()
    assert 0 < len(tradeable) < total, "fixture has no junk — recapture it"

    for c in tradeable:
        assert c.bid > 0 and c.ask >= c.bid and c.iv > 0
        assert c.mid > 0


def test_open_interest_is_joined_from_the_trading_api(real_spy_chain):
    """Open interest is NOT on the snapshot; it comes from OptionContract.

    This is the spec gap flagged in PROGRESS.md. If this assertion ever fails,
    the join has silently broken and the liquidity gate is running blind.
    """
    with_oi = [c for c in real_spy_chain.contracts if c.open_interest > 0]
    assert len(with_oi) > 50, "open-interest join produced nothing"
    assert max(c.open_interest for c in with_oi) > 100


# ---------------------------------------------------------------- selection


def test_expiry_and_strike_selection(real_spy_chain, real_as_of):
    chain = real_spy_chain
    nearest = chain.nearest_expiry(30, as_of=real_as_of)
    assert nearest is not None
    assert (nearest - real_as_of).days > 0

    window = chain.expiries_within(21, 45, as_of=real_as_of)
    for e in window:
        assert 21 <= (e - real_as_of).days <= 45

    atm = chain.atm_contract(nearest, "CALL")
    assert atm is not None
    assert abs(atm.strike - chain.spot) / chain.spot < 0.05


def test_by_expiry_partitions_the_chain(real_spy_chain):
    chain = real_spy_chain
    assert sum(len(chain.by_expiry(e)) for e in chain.expiries) == len(chain.contracts)


# ---------------------------------------------------------------- quote maths


def test_mid_and_spread_arithmetic():
    c = ContractQuote(
        symbol="SPY260918P00770000",
        underlying="SPY",
        strike=770.0,
        expiry=date(2026, 9, 18),
        right="PUT",
        bid=2.00,
        ask=2.20,
        iv=0.20,
    )
    assert c.mid == pytest.approx(2.10)
    assert c.spread_pct == pytest.approx(0.20 / 2.10)
    assert c.has_quote and c.is_tradeable


def test_zero_bid_is_not_tradeable():
    """A contract with no bid cannot be sold. Pricing off its ask is a fiction."""
    c = ContractQuote(
        symbol="SPY260918P00500000",
        underlying="SPY",
        strike=500.0,
        expiry=date(2026, 9, 18),
        right="PUT",
        bid=0.0,
        ask=0.05,
        iv=0.45,
    )
    assert not c.has_quote
    assert not c.is_tradeable
    assert c.spread_pct == 1.0


def test_missing_iv_is_not_tradeable():
    c = ContractQuote(
        symbol="SPY260918C00600000",
        underlying="SPY",
        strike=600.0,
        expiry=date(2026, 9, 18),
        right="CALL",
        bid=170.0,
        ask=172.0,
        iv=0.0,
    )
    assert c.has_quote
    assert not c.is_tradeable, "no IV means no vol view — the contract is unusable to us"


def test_mid_falls_back_to_last_trade_when_one_sided():
    c = ContractQuote(
        symbol="SPY260918P00770000",
        underlying="SPY",
        strike=770.0,
        expiry=date(2026, 9, 18),
        right="PUT",
        bid=0.0,
        ask=0.0,
        last=1.85,
        iv=0.2,
    )
    assert c.mid == pytest.approx(1.85)


def test_build_chain_sorts_and_tolerates_bad_keys():
    chain = build_chain("SPY", 100.0, {"GARBAGE": object()})
    assert chain.contracts == []
