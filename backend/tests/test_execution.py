"""Execution safety: atomicity, the sign convention, idempotency, exits.

docs/07-TESTING.md: "Credit/debit sign convention on mleg limit prices" and
"Idempotency: same client_order_id doesn't double-submit" are both listed as
non-negotiable. Getting the sign wrong inverts the trade and it would still
fill, which is the worst kind of bug: silent, and expensive.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from skew.config import Settings
from skew.exec.exit import CLOSING_INTENT, build_closing_structure, invert_leg
from skew.exec.monitor import (
    evaluate_exit,
    record_close,
    record_open,
    to_position,
    unrealised_pnl,
)
from skew.exec.submit import (
    SubmissionRefused,
    already_submitted,
    build_mleg_request,
    client_order_id,
    preflight,
    submit_structure,
)
from skew.models import Candidate, Leg
from skew.structures.base import assemble
from tests.test_gates import make_candidate, make_ctx, make_risk

EXPIRY = date(2026, 9, 30)


def _leg(strike, side, right, mid) -> Leg:
    return Leg(
        symbol=f"SPY{EXPIRY:%y%m%d}{right[0]}{round(strike * 1000):08d}",
        side=side,
        position_intent="STO" if side == "SELL" else "BTO",
        ratio_qty=1,
        strike=strike,
        expiry=EXPIRY,
        right=right,
        mid=mid,
        iv=0.20,
        delta=-0.25 if right == "PUT" else 0.25,
        gamma=0.01,
        theta=-0.05,
        vega=0.5,
        bid=mid - 0.05,
        ask=mid + 0.05,
        open_interest=5000,
    )


@pytest.fixture
def credit_spread():
    return assemble(
        "SPY",
        "PUT_CREDIT",
        [_leg(580, "SELL", "PUT", 2.00), _leg(575, "BUY", "PUT", 1.20)],
        spot=590.0,
        as_of=date(2026, 8, 30),
    )


@pytest.fixture
def debit_spread():
    return assemble(
        "SPY",
        "CALL_DEBIT",
        [_leg(580, "BUY", "CALL", 6.00), _leg(590, "SELL", "CALL", 2.50)],
        spot=580.0,
        as_of=date(2026, 8, 30),
    )


class FakeBroker:
    def __init__(self):
        self.submitted = []

    def submit_order(self, request):
        self.submitted.append(request)

        class Order:
            id = f"ord-{len(self.submitted)}"
            status = "accepted"

        return Order()


# ====================================================================
# Atomicity — never leg in
# ====================================================================


def test_a_spread_is_submitted_as_exactly_one_order(credit_spread):
    """Legging in means a window where the short leg is filled and the long one
    is not. That is a naked short option, which this desk must never hold."""
    from alpaca.trading.enums import OrderClass

    request = build_mleg_request(credit_spread, "cid-1")
    assert request.order_class == OrderClass.MLEG
    assert len(request.legs) == 2


def test_an_iron_condor_submits_four_legs_in_one_order():
    condor = assemble(
        "SPY",
        "IRON_CONDOR",
        [
            _leg(570, "SELL", "PUT", 2.00),
            _leg(565, "BUY", "PUT", 1.30),
            _leg(610, "SELL", "CALL", 1.80),
            _leg(615, "BUY", "CALL", 0.90),
        ],
        spot=590.0,
        as_of=date(2026, 8, 30),
    )
    assert len(build_mleg_request(condor, "cid").legs) == 4


def test_position_intent_is_set_on_every_leg(credit_spread):
    """Required by Alpaca for mleg orders."""
    from alpaca.trading.enums import PositionIntent

    request = build_mleg_request(credit_spread, "cid")
    intents = {leg.position_intent for leg in request.legs}
    assert intents <= {PositionIntent.SELL_TO_OPEN, PositionIntent.BUY_TO_OPEN}
    assert all(leg.position_intent is not None for leg in request.legs)


def test_ratio_quantities_reach_the_request_normalised(credit_spread):
    assert [leg.ratio_qty for leg in build_mleg_request(credit_spread, "cid").legs] == [1, 1]


# ====================================================================
# The sign convention — positive is a debit, negative is a credit
# ====================================================================


def test_a_credit_spread_submits_a_negative_limit(credit_spread):
    request = build_mleg_request(credit_spread, "cid")
    assert float(request.limit_price) == pytest.approx(-80.0)
    assert float(request.limit_price) < 0


def test_a_debit_spread_submits_a_positive_limit(debit_spread):
    request = build_mleg_request(debit_spread, "cid")
    assert float(request.limit_price) == pytest.approx(350.0)
    assert float(request.limit_price) > 0


def test_the_sign_cannot_be_inverted_by_construction(credit_spread, debit_spread):
    """limit_price is derived from net_credit in exactly one place.

    Because it is derived rather than passed, a credit structure cannot carry a
    debit limit — there is no field to set wrongly. This pins that relationship
    so a future refactor that reintroduces a settable limit price fails here.
    """
    assert credit_spread.limit_price == pytest.approx(-credit_spread.net_credit)
    assert debit_spread.limit_price == pytest.approx(-debit_spread.net_credit)
    assert credit_spread.is_credit and credit_spread.limit_price < 0
    assert not debit_spread.is_credit and debit_spread.limit_price > 0


def test_a_zero_priced_structure_is_refused_rather_than_submitted(credit_spread):
    """A structure worth nothing has no defensible limit price in either
    direction, and the guard refuses it rather than sending a zero."""
    degenerate = credit_spread.model_copy(update={"net_credit": 0.0})
    with pytest.raises(SubmissionRefused, match="invert the trade"):
        build_mleg_request(degenerate, "cid")


def test_market_orders_carry_no_limit_price(credit_spread):
    request = build_mleg_request(credit_spread, "cid", use_limit=False)
    assert not hasattr(request, "limit_price") or request.limit_price is None


# ====================================================================
# Idempotency
# ====================================================================


def test_client_order_ids_are_unique_per_submission(credit_spread):
    ids = {client_order_id(credit_spread) for _ in range(50)}
    assert len(ids) == 50


def test_client_order_id_is_prefixed_and_bounded(credit_spread):
    cid = client_order_id(credit_spread)
    assert cid.startswith("skew-SPY-")
    assert len(cid) <= 64


def test_the_same_client_order_id_does_not_create_a_second_order(credit_spread):
    """A retry after a network timeout must not double-fill."""
    from skew.exec.submit import _persist_order

    record = {
        "client_order_id": "skew-dupe-test",
        "broker_order_id": "b1",
        "status": "accepted",
        "symbol": "SPY",
        "structure_id": credit_spread.id,
        "kind": credit_spread.kind,
        "qty": 1,
        "limit_price": -80.0,
        "net_credit": 80.0,
        "max_loss": 420.0,
        "legs": [],
        "submitted_at": datetime.now(UTC).isoformat(),
    }
    _persist_order(record)
    assert already_submitted("skew-dupe-test")

    _persist_order({**record, "broker_order_id": "b2"})
    from skew.audit.models import OrderRow
    from skew.db import session_scope

    with session_scope() as session:
        assert session.get(OrderRow, "skew-dupe-test").broker_order_id == "b1"


# ====================================================================
# Pre-flight recheck
# ====================================================================


def test_preflight_reruns_the_gate_chain_before_submitting():
    """Market data moves between candidate construction and order placement."""
    candidate = make_candidate()
    candidate.passed_all = True
    ctx = make_ctx(risk=make_risk(budget=10_000.0))
    assert preflight(candidate, ctx).passed_all


def test_preflight_refuses_when_the_market_has_moved():
    from skew.exec.submit import PreflightFailed

    candidate = make_candidate()
    candidate.passed_all = True
    # Budget collapsed since the candidate was built.
    with pytest.raises(PreflightFailed, match="market moved"):
        preflight(candidate, make_ctx(risk=make_risk(budget=50.0)))


def test_submission_runs_preflight_by_default(credit_spread):
    from skew.exec.submit import PreflightFailed

    candidate = make_candidate()
    candidate.passed_all = True
    with pytest.raises(PreflightFailed):
        submit_structure(FakeBroker(), candidate, make_ctx(risk=make_risk(budget=50.0)))


def test_the_kill_switch_halts_submission(credit_spread):
    candidate = Candidate(structure=credit_spread, passed_all=True)
    cfg = Settings(kill_switch=True)
    with pytest.raises(SubmissionRefused, match="Kill switch"):
        submit_structure(FakeBroker(), candidate, make_ctx(), settings=cfg, skip_preflight=True)


def test_a_successful_submission_records_the_order(credit_spread):
    broker = FakeBroker()
    candidate = Candidate(structure=credit_spread, passed_all=True)
    record = submit_structure(broker, candidate, make_ctx(), skip_preflight=True)

    assert len(broker.submitted) == 1, "exactly one order, never two"
    assert record["broker_order_id"] == "ord-1"
    assert record["limit_price"] == pytest.approx(-80.0)
    assert already_submitted(record["client_order_id"])


# ====================================================================
# Closing — also atomic, sign inverted
# ====================================================================


def test_closing_intents_are_the_inverse_of_opening():
    assert CLOSING_INTENT == {"BTO": "STC", "STO": "BTC", "BTC": "STO", "STC": "BTO"}


def test_inverting_a_leg_flips_side_and_intent():
    leg = _leg(580, "SELL", "PUT", 2.00)
    flipped = invert_leg(leg)
    assert flipped.side == "BUY"
    assert flipped.position_intent == "BTC"
    assert flipped.symbol == leg.symbol and flipped.strike == leg.strike


def test_closing_a_credit_spread_is_a_debit(credit_spread):
    """We sold it; we buy it back. The limit sign must flip."""
    closing = build_closing_structure(credit_spread)
    assert closing.net_credit < 0, "closing a credit spread costs money"
    assert closing.limit_price > 0, "a debit takes a positive limit price"
    assert credit_spread.limit_price < 0


def test_closing_prices_from_live_mids_when_supplied(credit_spread):
    short = next(leg for leg in credit_spread.legs if leg.side == "SELL")
    long_leg = next(leg for leg in credit_spread.legs if leg.side == "BUY")
    mids = {short.symbol: 4.00, long_leg.symbol: 1.50}

    closing = build_closing_structure(credit_spread, mids)
    # Buy back the short at 4.00, sell the long at 1.50 -> pay 2.50 -> $250.
    assert closing.net_credit == pytest.approx(-250.0)


def test_a_closing_order_is_still_one_atomic_order(credit_spread):
    from alpaca.trading.enums import OrderClass

    closing = build_closing_structure(credit_spread)
    request = build_mleg_request(closing, "cid-close")
    assert request.order_class == OrderClass.MLEG
    assert len(request.legs) == 2


# ====================================================================
# Exit rules
# ====================================================================


def test_profit_target_fires_at_half_the_credit(credit_spread):
    short = next(leg for leg in credit_spread.legs if leg.side == "SELL")
    long_leg = next(leg for leg in credit_spread.legs if leg.side == "BUY")
    # Spread narrowed from 0.80 to 0.40 -> half the credit captured.
    mids = {short.symbol: 1.00, long_leg.symbol: 0.60}

    assert unrealised_pnl(credit_spread, mids) == pytest.approx(40.0)
    signal = evaluate_exit(credit_spread, mids, as_of=date(2026, 8, 30))
    assert signal.should_exit
    assert signal.rule == "profit_target"
    assert "50%" in signal.reason


def test_no_exit_while_the_position_is_working(credit_spread):
    short = next(leg for leg in credit_spread.legs if leg.side == "SELL")
    long_leg = next(leg for leg in credit_spread.legs if leg.side == "BUY")
    mids = {short.symbol: 1.80, long_leg.symbol: 1.10}
    assert not evaluate_exit(credit_spread, mids, as_of=date(2026, 8, 30))


def test_loss_limit_fires_at_the_configured_multiple(credit_spread):
    short = next(leg for leg in credit_spread.legs if leg.side == "SELL")
    long_leg = next(leg for leg in credit_spread.legs if leg.side == "BUY")
    # Spread widened from 0.80 to 2.60 -> down $180, more than 2x the $80 credit.
    mids = {short.symbol: 4.00, long_leg.symbol: 1.40}

    signal = evaluate_exit(credit_spread, mids, as_of=date(2026, 8, 30))
    assert signal.should_exit
    assert signal.rule == "loss_limit"
    assert "falsified" in signal.reason


def test_dte_threshold_fires_in_the_final_week(credit_spread):
    short = next(leg for leg in credit_spread.legs if leg.side == "SELL")
    long_leg = next(leg for leg in credit_spread.legs if leg.side == "BUY")
    mids = {short.symbol: 1.90, long_leg.symbol: 1.15}

    # Threshold is 2 days for the 7-14 DTE competition window — inside it fires,
    # just outside it must not (a 7-DTE entry would otherwise close on day one).
    calm = evaluate_exit(credit_spread, mids, as_of=EXPIRY - timedelta(days=5))
    assert calm.rule != "dte"
    signal = evaluate_exit(credit_spread, mids, as_of=EXPIRY - timedelta(days=2))
    assert signal.should_exit
    assert signal.rule == "dte"
    assert "Gamma rises sharply" in signal.reason


def test_the_deadline_overrides_everything(credit_spread):
    short = next(leg for leg in credit_spread.legs if leg.side == "SELL")
    long_leg = next(leg for leg in credit_spread.legs if leg.side == "BUY")
    mids = {short.symbol: 1.90, long_leg.symbol: 1.15}
    cfg = Settings(deadline_utc="2020-01-01T00:00:00+00:00")

    signal = evaluate_exit(credit_spread, mids, as_of=date(2026, 8, 30), settings=cfg)
    assert signal.should_exit
    assert signal.rule == "deadline"


def test_a_malformed_deadline_is_logged_not_fatal(credit_spread):
    short = next(leg for leg in credit_spread.legs if leg.side == "SELL")
    long_leg = next(leg for leg in credit_spread.legs if leg.side == "BUY")
    mids = {short.symbol: 1.90, long_leg.symbol: 1.15}
    cfg = Settings(deadline_utc="not-a-timestamp")
    assert not evaluate_exit(credit_spread, mids, as_of=date(2026, 8, 30), settings=cfg)


# ====================================================================
# Position persistence
# ====================================================================


def test_a_position_is_recorded_as_one_structure_not_n_legs(credit_spread):
    """Alpaca reports positions leg by leg; the exit rules only work at the
    structure level."""
    record_open(credit_spread, "cid-1")
    from skew.exec.monitor import open_positions

    rows = open_positions()
    assert len(rows) == 1
    assert rows[0].id == credit_spread.id
    assert len(rows[0].legs) == 2

    position = to_position(rows[0], mids={})
    assert position.symbol == "SPY"
    assert position.max_loss == pytest.approx(420.0)


def test_recording_the_same_position_twice_does_not_duplicate(credit_spread):
    from skew.exec.monitor import open_positions

    record_open(credit_spread, "cid-1")
    record_open(credit_spread, "cid-2")
    assert len(open_positions()) == 1


def test_closing_a_position_removes_it_from_the_open_set(credit_spread):
    from skew.exec.monitor import open_positions

    record_open(credit_spread, "cid-1")
    record_close(credit_spread.id, realized_pnl=40.0, reason="profit target")
    assert open_positions() == []


def test_a_live_cycle_downgrades_itself_when_the_market_is_closed(monkeypatch):
    """Defence in depth against submitting into a closed market.

    The scheduler already skips closed markets, but a live cycle can also come
    from the CLI or from a redeploy. Queuing an order nobody is watching is the
    failure this guards.
    """
    from skew import loop

    class ClosedDesk:
        broker = None
        settings = Settings()

        def start_cycle(self):
            pass

        def market_open(self):
            return False

        def equity(self):
            return 100_000.0

        def evaluate_symbol(self, symbol):
            from skew.desk import SymbolResult

            return SymbolResult(symbol=symbol, error="stubbed")

    monkeypatch.setattr(loop, "_monitor", lambda *a, **k: [])
    report = loop.run_cycle(dry_run=False, settings=Settings(universe="SPY"), desk=ClosedDesk())
    assert any("market closed" in e for e in report.errors)
