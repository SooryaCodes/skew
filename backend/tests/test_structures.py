"""Structure arithmetic against hand-worked examples.

docs/07-TESTING.md: "Max loss for every structure type, against hand-worked
examples. A put credit spread with strikes 580/575 and $0.80 credit has a max
loss of $420. Assert it."

Every number in this file was worked out on paper first.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from skew.data.chains import ContractQuote
from skew.models import Leg, Structure
from skew.structures.base import (
    StructureError,
    assemble,
    compute_risk,
    leg_from_contract,
    net_credit,
    net_greek,
    normalise_ratios,
    structure_id,
)
from skew.structures.credit import (
    build_credit_candidates,
    call_credit_spread,
    iron_condor,
    put_credit_spread,
)
from skew.structures.debit import build_debit_candidates, call_debit_spread, put_debit_spread
from skew.structures.selection import by_delta, choose_expiry, strikes_away, usable_contracts

EXPIRY = date(2026, 9, 18)


def _leg(strike, side, right, mid, *, delta=0.0, vega=0.0, theta=0.0, gamma=0.0, ratio=1) -> Leg:
    return Leg(
        symbol=f"SPY{EXPIRY:%y%m%d}{right[0]}{round(strike * 1000):08d}",
        side=side,
        position_intent="STO" if side == "SELL" else "BTO",
        ratio_qty=ratio,
        strike=strike,
        expiry=EXPIRY,
        right=right,
        mid=mid,
        iv=0.20,
        delta=delta,
        gamma=gamma,
        theta=theta,
        vega=vega,
        bid=mid - 0.02,
        ask=mid + 0.02,
        open_interest=5000,
    )


# ====================================================================
# The worked example from docs/04-OPTIONS-PRIMER.md §5
# ====================================================================


@pytest.fixture
def primer_put_credit() -> list[Leg]:
    """SELL 580 put @ $2.00, BUY 575 put @ $1.20. Net credit $0.80 -> $80."""
    return [
        _leg(580, "SELL", "PUT", 2.00, delta=-0.30, vega=0.55, theta=-0.09),
        _leg(575, "BUY", "PUT", 1.20, delta=-0.20, vega=0.45, theta=-0.07),
    ]


def test_primer_put_credit_spread_arithmetic(primer_put_credit):
    """max profit $80, max loss $420, breakeven 579.20. From the primer."""
    credit = net_credit(primer_put_credit)
    assert credit == pytest.approx(80.0)

    max_loss, max_profit, breakevens = compute_risk("PUT_CREDIT", primer_put_credit, credit)
    assert max_profit == pytest.approx(80.0)
    assert max_loss == pytest.approx(420.0)  # (580 − 575) × 100 − 80
    assert breakevens == [pytest.approx(579.20)]


def test_primer_put_credit_spread_assembles(primer_put_credit):
    s = assemble("SPY", "PUT_CREDIT", primer_put_credit, spot=590.0, as_of=date(2026, 8, 30))
    assert s.net_credit == pytest.approx(80.0)
    assert s.max_loss == pytest.approx(420.0)
    assert s.max_profit == pytest.approx(80.0)
    assert s.breakevens == [pytest.approx(579.20)]
    assert s.dte == 19
    assert s.is_credit
    assert s.width == 5.0


def test_max_loss_plus_max_profit_equals_the_width(primer_put_credit):
    """A sanity identity for every vertical: risk + reward = width × 100."""
    s = assemble("SPY", "PUT_CREDIT", primer_put_credit, spot=590.0)
    assert s.max_loss + s.max_profit == pytest.approx(s.width * 100)


# ====================================================================
# Sign conventions — the ones that invert a trade when wrong
# ====================================================================


def test_net_credit_is_positive_when_money_comes_in(primer_put_credit):
    assert net_credit(primer_put_credit) > 0


def test_limit_price_is_negative_for_a_credit(primer_put_credit):
    """Alpaca mleg convention: positive limit = debit, negative = credit.

    Inverting this sign inverts the trade. It is derived in exactly one place.
    """
    s = assemble("SPY", "PUT_CREDIT", primer_put_credit, spot=590.0)
    assert s.limit_price == pytest.approx(-80.0)
    assert s.limit_price < 0


def test_limit_price_is_positive_for_a_debit():
    legs = [
        _leg(580, "BUY", "CALL", 6.00, delta=0.55),
        _leg(590, "SELL", "CALL", 2.50, delta=0.30),
    ]
    s = assemble("SPY", "CALL_DEBIT", legs, spot=580.0)
    assert s.net_credit == pytest.approx(-350.0)
    assert s.limit_price == pytest.approx(350.0)
    assert s.limit_price > 0
    assert not s.is_credit


def test_short_premium_is_negative_vega_and_positive_theta(primer_put_credit):
    """We are a vega business. A premium sale must show short vega.

    net_vega = (−1 × 0.55 + 1 × 0.45) × 100 = −10
    net_theta = (−1 × −0.09 + 1 × −0.07) × 100 = +2
    """
    assert net_greek(primer_put_credit, "vega") == pytest.approx(-10.0)
    assert net_greek(primer_put_credit, "theta") == pytest.approx(2.0)

    s = assemble("SPY", "PUT_CREDIT", primer_put_credit, spot=590.0)
    assert s.net_vega < 0, "selling premium is a short-volatility position"
    assert s.net_theta > 0, "selling premium collects time decay"


def test_put_credit_spread_has_positive_net_delta(primer_put_credit):
    """net_delta = (−1 × −0.30 + 1 × −0.20) × 100 = +10.

    Positive: the position gains as the underlying rises. Small, because the
    structure is direction-tolerant by design.
    """
    assert net_greek(primer_put_credit, "delta") == pytest.approx(10.0)


def test_quantity_scales_every_cash_number_linearly(primer_put_credit):
    one = assemble("SPY", "PUT_CREDIT", primer_put_credit, spot=590.0, qty=1)
    three = assemble("SPY", "PUT_CREDIT", primer_put_credit, spot=590.0, qty=3)
    assert three.net_credit == pytest.approx(one.net_credit * 3)
    assert three.max_loss == pytest.approx(one.max_loss * 3)
    assert three.net_vega == pytest.approx(one.net_vega * 3)
    # Breakeven is per-share and must NOT scale with quantity.
    assert three.breakevens == pytest.approx(one.breakevens)


# ====================================================================
# Other structure types, hand-worked
# ====================================================================


def test_call_credit_spread_arithmetic():
    """SELL 600 call @ $2.50, BUY 605 call @ $1.30. Credit $1.20 -> $120.

    max loss = 5 × 100 − 120 = $380. Breakeven = 600 + 1.20 = 601.20.
    """
    legs = [
        _leg(600, "SELL", "CALL", 2.50, delta=0.28, vega=0.50),
        _leg(605, "BUY", "CALL", 1.30, delta=0.18, vega=0.42),
    ]
    s = assemble("SPY", "CALL_CREDIT", legs, spot=590.0)
    assert s.net_credit == pytest.approx(120.0)
    assert s.max_loss == pytest.approx(380.0)
    assert s.max_profit == pytest.approx(120.0)
    assert s.breakevens == [pytest.approx(601.20)]
    assert s.net_delta < 0, "a call credit spread is short delta"
    assert s.net_vega < 0


def test_call_debit_spread_arithmetic():
    """BUY 580 call @ $6.00, SELL 590 call @ $2.50. Debit $3.50 -> $350.

    The debit paid IS the max loss. max profit = 10 × 100 − 350 = $650.
    Breakeven = 580 + 3.50 = 583.50.
    """
    legs = [
        _leg(580, "BUY", "CALL", 6.00, delta=0.55, vega=0.70),
        _leg(590, "SELL", "CALL", 2.50, delta=0.30, vega=0.55),
    ]
    s = assemble("SPY", "CALL_DEBIT", legs, spot=580.0)
    assert s.net_credit == pytest.approx(-350.0)
    assert s.max_loss == pytest.approx(350.0)
    assert s.max_profit == pytest.approx(650.0)
    assert s.breakevens == [pytest.approx(583.50)]
    assert s.net_vega > 0, "buying premium is a long-volatility position"
    assert s.net_theta <= 0, "buying premium pays time decay"


def test_put_debit_spread_arithmetic():
    """BUY 580 put @ $6.00, SELL 570 put @ $2.50. Debit $350.

    max profit = 10 × 100 − 350 = $650. Breakeven = 580 − 3.50 = 576.50.
    """
    legs = [
        _leg(580, "BUY", "PUT", 6.00, delta=-0.50, vega=0.70),
        _leg(570, "SELL", "PUT", 2.50, delta=-0.28, vega=0.55),
    ]
    s = assemble("SPY", "PUT_DEBIT", legs, spot=580.0)
    assert s.max_loss == pytest.approx(350.0)
    assert s.max_profit == pytest.approx(650.0)
    assert s.breakevens == [pytest.approx(576.50)]


def test_iron_condor_arithmetic():
    """Four legs. Put wing 570/565, call wing 610/615, total credit $1.60 -> $160.

    Only ONE wing can finish in the money, so max loss is the wider wing minus
    the credit — 5 × 100 − 160 = $340 — not the sum of both wings.
    Breakevens: 570 − 1.60 = 568.40 and 610 + 1.60 = 611.60.
    """
    legs = [
        _leg(570, "SELL", "PUT", 2.00, delta=-0.20, vega=0.50),
        _leg(565, "BUY", "PUT", 1.30, delta=-0.14, vega=0.42),
        _leg(610, "SELL", "CALL", 1.80, delta=0.20, vega=0.48),
        _leg(615, "BUY", "CALL", 0.90, delta=0.13, vega=0.40),
    ]
    s = assemble("SPY", "IRON_CONDOR", legs, spot=590.0)
    assert len(s.legs) == 4
    assert s.net_credit == pytest.approx(160.0)
    assert s.max_loss == pytest.approx(340.0)
    assert s.max_profit == pytest.approx(160.0)
    assert s.breakevens == [pytest.approx(568.40), pytest.approx(611.60)]
    assert s.net_vega < 0


def test_iron_condor_with_unequal_wings_uses_the_wider_one():
    """Put wing 10 wide, call wing 5 wide, credit $200. Worst case is 10 × 100 − 200."""
    legs = [
        _leg(570, "SELL", "PUT", 2.50),
        _leg(560, "BUY", "PUT", 1.30),
        _leg(610, "SELL", "CALL", 1.80),
        _leg(615, "BUY", "CALL", 1.00),
    ]
    s = assemble("SPY", "IRON_CONDOR", legs, spot=590.0)
    assert s.net_credit == pytest.approx(200.0)
    assert s.max_loss == pytest.approx(800.0)


# ====================================================================
# The rules that get orders rejected
# ====================================================================


def test_ratio_gcd_is_normalised():
    """A 2:4 spread is rejected by Alpaca. It must be sent as 1:2."""
    legs = [
        _leg(580, "SELL", "PUT", 2.00, ratio=2),
        _leg(575, "BUY", "PUT", 1.20, ratio=4),
    ]
    assert [leg.ratio_qty for leg in normalise_ratios(legs)] == [1, 2]


@pytest.mark.parametrize(
    ("ratios", "expected"),
    [((2, 4), [1, 2]), ((3, 6), [1, 2]), ((4, 4), [1, 1]), ((1, 2), [1, 2]), ((2, 3), [2, 3])],
)
def test_ratio_normalisation_cases(ratios, expected):
    legs = [
        _leg(580, "SELL", "PUT", 2.00, ratio=ratios[0]),
        _leg(575, "BUY", "PUT", 1.20, ratio=ratios[1]),
    ]
    assert [leg.ratio_qty for leg in normalise_ratios(legs)] == expected


def test_structure_model_rejects_a_bad_gcd_directly():
    """Belt and braces: even bypassing assemble(), the model refuses."""
    with pytest.raises(ValidationError, match="GCD 1"):
        Structure(
            id="x",
            symbol="SPY",
            kind="PUT_CREDIT",
            legs=[
                _leg(580, "SELL", "PUT", 2.00, ratio=2),
                _leg(575, "BUY", "PUT", 1.20, ratio=4),
            ],
            net_credit=80.0,
            max_loss=420.0,
            max_profit=80.0,
            breakevens=[579.2],
            net_delta=0,
            net_vega=0,
            net_theta=0,
            dte=19,
        )


def test_structure_cannot_exist_without_a_positive_max_loss():
    """A structure whose worst case is unknown is a bug, not an edge case."""
    for bad in (0.0, -100.0):
        with pytest.raises(ValidationError, match="max_loss must be positive"):
            Structure(
                id="x",
                symbol="SPY",
                kind="PUT_CREDIT",
                legs=[_leg(580, "SELL", "PUT", 2.0), _leg(575, "BUY", "PUT", 1.2)],
                net_credit=80.0,
                max_loss=bad,
                max_profit=80.0,
                breakevens=[579.2],
                net_delta=0,
                net_vega=0,
                net_theta=0,
                dte=19,
            )


def test_alpaca_leg_count_limits_are_enforced():
    """Options mleg orders take 2–4 legs. An iron condor is exactly 4.

    Enforced twice: assemble() rejects early so the message names the real
    problem, and the model rejects independently for anything bypassing it.
    """
    with pytest.raises(StructureError, match="2–4 legs"):
        assemble("SPY", "PUT_CREDIT", [_leg(580, "SELL", "PUT", 2.0)], spot=590.0)

    five = [_leg(570 + i * 5, "SELL" if i % 2 else "BUY", "PUT", 2.0) for i in range(5)]
    with pytest.raises(StructureError, match="2–4 legs"):
        assemble("SPY", "IRON_CONDOR", five, spot=590.0)

    with pytest.raises(ValidationError, match="2–4 legs"):
        Structure(
            id="x",
            symbol="SPY",
            kind="PUT_CREDIT",
            legs=[_leg(580, "SELL", "PUT", 2.0)],
            net_credit=200.0,
            max_loss=420.0,
            max_profit=200.0,
            breakevens=[578.0],
            net_delta=0,
            net_vega=0,
            net_theta=0,
            dte=19,
        )


def test_position_intent_is_set_on_every_leg():
    """Required by Alpaca for mleg, and derived rather than passed."""
    c = ContractQuote(
        symbol="SPY260918P00580000",
        underlying="SPY",
        strike=580.0,
        expiry=EXPIRY,
        right="PUT",
        bid=1.98,
        ask=2.02,
        iv=0.2,
    )
    assert leg_from_contract(c, "SELL", opening=True).position_intent == "STO"
    assert leg_from_contract(c, "BUY", opening=True).position_intent == "BTO"
    assert leg_from_contract(c, "BUY", opening=False).position_intent == "BTC"
    assert leg_from_contract(c, "SELL", opening=False).position_intent == "STC"


def test_leg_refuses_a_contract_with_no_price():
    c = ContractQuote(
        symbol="SPY260918P00500000",
        underlying="SPY",
        strike=500.0,
        expiry=EXPIRY,
        right="PUT",
        bid=0.0,
        ask=0.0,
        iv=0.4,
    )
    with pytest.raises(StructureError, match="no usable price"):
        leg_from_contract(c, "SELL")


def test_a_credit_structure_priced_as_a_debit_is_refused():
    """Stale quotes can make the long leg dearer than the short. That is not a
    credit spread, and building it anyway would misreport the max loss."""
    legs = [_leg(580, "SELL", "PUT", 1.00), _leg(575, "BUY", "PUT", 1.50)]
    with pytest.raises(StructureError, match="must be opened for a credit"):
        assemble("SPY", "PUT_CREDIT", legs, spot=590.0)


def test_a_debit_structure_priced_as_a_credit_is_refused():
    legs = [_leg(580, "BUY", "CALL", 1.00), _leg(590, "SELL", "CALL", 1.50)]
    with pytest.raises(StructureError, match="must be opened for a debit"):
        assemble("SPY", "CALL_DEBIT", legs, spot=580.0)


def test_structure_id_is_deterministic_and_readable():
    legs = [_leg(580, "SELL", "PUT", 2.0), _leg(575, "BUY", "PUT", 1.2)]
    a = structure_id("SPY", "PUT_CREDIT", EXPIRY, legs)
    b = structure_id("SPY", "PUT_CREDIT", EXPIRY, list(reversed(legs)))
    assert a == b, "leg order must not change the id"
    assert a == "SPY:PUT_CREDIT:260918:575-580"


# ====================================================================
# Against real chains
# ====================================================================


def test_build_put_credit_spread_from_a_real_chain(real_spy_chain, real_as_of):
    s = put_credit_spread(real_spy_chain, dte_min=14, dte_max=60, as_of=real_as_of)
    assert s is not None
    assert s.kind == "PUT_CREDIT"
    assert len(s.legs) == 2
    assert s.max_loss > 0
    assert s.net_credit > 0
    assert s.max_loss + s.max_profit == pytest.approx(s.width * 100, abs=0.01)

    short = next(leg for leg in s.legs if leg.side == "SELL")
    long_leg = next(leg for leg in s.legs if leg.side == "BUY")
    assert short.strike > long_leg.strike, "the protective put must be further OTM"
    assert short.right == long_leg.right == "PUT"
    assert 0.05 < abs(short.delta) < 0.50


def test_build_call_credit_spread_from_a_real_chain(real_spy_chain, real_as_of):
    s = call_credit_spread(real_spy_chain, dte_min=14, dte_max=60, as_of=real_as_of)
    assert s is not None
    short = next(leg for leg in s.legs if leg.side == "SELL")
    long_leg = next(leg for leg in s.legs if leg.side == "BUY")
    assert short.strike < long_leg.strike
    assert s.net_credit > 0 and s.max_loss > 0


def test_build_iron_condor_from_a_real_chain(real_spy_chain, real_as_of):
    s = iron_condor(real_spy_chain, dte_min=14, dte_max=60, as_of=real_as_of)
    assert s is not None
    assert len(s.legs) == 4
    assert s.net_credit > 0
    assert len(s.breakevens) == 2
    assert s.breakevens[0] < s.spot < s.breakevens[1], "spot must sit inside the condor"


def test_build_debit_spreads_from_a_real_chain(real_spy_chain, real_as_of):
    for builder in (call_debit_spread, put_debit_spread):
        s = builder(real_spy_chain, dte_min=14, dte_max=60, as_of=real_as_of)
        assert s is not None, builder.__name__
        assert s.net_credit < 0, "a debit spread costs money"
        assert s.max_loss == pytest.approx(-s.net_credit)
        assert s.net_vega > 0, "buying premium is long volatility"


def test_every_real_structure_has_a_computed_max_loss(real_spy_chain, real_as_of):
    built = build_credit_candidates(
        real_spy_chain, dte_min=14, dte_max=60, as_of=real_as_of
    ) + build_debit_candidates(real_spy_chain, dte_min=14, dte_max=60, as_of=real_as_of)
    assert len(built) >= 3
    for s in built:
        assert s.max_loss > 0
        assert 2 <= len(s.legs) <= 4
        assert all(leg.position_intent in ("BTO", "STO") for leg in s.legs)


def test_no_structure_ever_contains_an_unprotected_short(real_spy_chain, real_as_of):
    """The defined-risk invariant. Every short leg must have a long leg of the
    same right, in the same expiry, protecting it."""
    built = build_credit_candidates(
        real_spy_chain, dte_min=14, dte_max=60, as_of=real_as_of
    ) + build_debit_candidates(real_spy_chain, dte_min=14, dte_max=60, as_of=real_as_of)

    for s in built:
        for short in (leg for leg in s.legs if leg.side == "SELL"):
            covers = [
                leg
                for leg in s.legs
                if leg.side == "BUY" and leg.right == short.right and leg.expiry == short.expiry
            ]
            assert covers, f"{s.id} has a naked short {short.right} at {short.strike}"


def test_liquidity_prefilter_excludes_junk(real_spy_chain, real_as_of):
    expiry = choose_expiry(real_spy_chain, 14, 60, as_of=real_as_of)
    assert expiry is not None
    loose = usable_contracts(real_spy_chain, expiry, "PUT", 0, 1.0)
    strict = usable_contracts(real_spy_chain, expiry, "PUT", 500, 0.10)
    assert 0 < len(strict) < len(loose)
    assert all(c.open_interest >= 500 and c.spread_pct <= 0.10 for c in strict)


def test_strike_stepping_walks_listed_strikes_not_dollar_distance(real_spy_chain, real_as_of):
    """Real chains mix $1 and $5 spacing, so arithmetic on price is wrong."""
    expiry = choose_expiry(real_spy_chain, 14, 60, as_of=real_as_of)
    assert expiry is not None
    contracts = usable_contracts(real_spy_chain, expiry, "PUT", 100, 0.5)
    anchor = by_delta(contracts, 0.25)
    assert anchor is not None

    lower = strikes_away(contracts, anchor, 2, -1)
    assert lower is not None and lower.strike < anchor.strike
    higher = strikes_away(contracts, anchor, 2, 1)
    assert higher is not None and higher.strike > anchor.strike
    assert strikes_away(contracts, anchor, 10_000, 1) is None


def test_target_width_is_configurable_end_to_end(real_spy_chain, real_as_of):
    """The config knob must actually reach the builders.

    It did not: `target_width_pct` existed in Settings and was threaded through
    selection.py, but desk.py never passed it, so every structure silently used
    the module default and the setting did nothing. Caught by setting it and
    seeing identical max losses come back.
    """
    narrow = build_credit_candidates(
        real_spy_chain, dte_min=14, dte_max=60, width_pct=0.004, as_of=real_as_of
    )
    wide = build_credit_candidates(
        real_spy_chain, dte_min=14, dte_max=60, width_pct=0.02, as_of=real_as_of
    )
    assert narrow and wide
    assert max(s.width for s in wide) > max(s.width for s in narrow)
    assert max(s.max_loss for s in wide) > max(s.max_loss for s in narrow)


def test_the_desk_passes_its_configured_width(real_spy_chain, real_as_of):
    """Guards the specific wiring gap, at the seam where it was missing."""
    import inspect

    from skew.desk import Desk

    source = inspect.getsource(Desk._build_structures)
    assert "width_pct" in source, "desk must forward the configured width to the builders"
    assert "cfg.target_width_pct" in source
