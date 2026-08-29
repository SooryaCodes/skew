"""The gate chain — the most heavily tested part of the system.

docs/07-TESTING.md, non-negotiable:

* Each gate independently, pass and fail, with a synthetic candidate.
* Backwardation must **always** block a premium-selling structure. Test it hard.
* The stress gate must fail when any cell breaches, and the returned ``detail``
  must identify the correct cell.
* The budget gate must respect the current tier.
"""

from __future__ import annotations

from datetime import date

import pytest

from skew.data.calendar import EarningsCalendar
from skew.gates.base import GateContext, default_gates, run_gates, summarise
from skew.gates.budget import budget_gate
from skew.gates.earnings import earnings_gate
from skew.gates.liquidity import liquidity_gate
from skew.gates.stress import stress_gate
from skew.gates.term_structure import term_structure_gate
from skew.models import Candidate, GateResult, Leg, RiskAuthority, TermPoint, VolState
from skew.structures.base import assemble
from skew.vol.term import TermStructure

AS_OF = date(2026, 8, 30)
EXPIRY = date(2026, 9, 30)


def _leg(strike, side, right, mid, *, oi=5000, bid=None, ask=None, iv=0.20) -> Leg:
    return Leg(
        symbol=f"SPY{EXPIRY:%y%m%d}{right[0]}{round(strike * 1000):08d}",
        side=side,
        position_intent="STO" if side == "SELL" else "BTO",
        ratio_qty=1,
        strike=strike,
        expiry=EXPIRY,
        right=right,
        mid=mid,
        iv=iv,
        delta=-0.25 if right == "PUT" else 0.25,
        gamma=0.01,
        theta=-0.05,
        vega=0.5,
        bid=mid - 0.05 if bid is None else bid,
        ask=mid + 0.05 if ask is None else ask,
        open_interest=oi,
    )


def make_structure(kind="PUT_CREDIT", symbol="SPY", **leg_kwargs):
    if kind == "PUT_CREDIT":
        legs = [
            _leg(580, "SELL", "PUT", 2.00, **leg_kwargs),
            _leg(575, "BUY", "PUT", 1.20, **leg_kwargs),
        ]
    elif kind == "CALL_CREDIT":
        legs = [
            _leg(600, "SELL", "CALL", 2.50, **leg_kwargs),
            _leg(605, "BUY", "CALL", 1.30, **leg_kwargs),
        ]
    else:  # CALL_DEBIT
        legs = [
            _leg(580, "BUY", "CALL", 6.00, **leg_kwargs),
            _leg(590, "SELL", "CALL", 2.50, **leg_kwargs),
        ]
    for leg in legs:
        leg.symbol = leg.symbol.replace("SPY", symbol, 1)
    return assemble(symbol, kind, legs, spot=590.0, as_of=AS_OF)


def make_candidate(kind="PUT_CREDIT", symbol="SPY", **leg_kwargs) -> Candidate:
    return Candidate(structure=make_structure(kind, symbol, **leg_kwargs))


def make_vol_state(symbol="SPY", regime="SELL_VOL") -> VolState:
    return VolState(
        symbol=symbol,
        spot=590.0,
        iv_atm=0.24,
        rv_20=0.10,
        rv_parkinson=0.09,
        vrp=0.14,
        rv_percentile=40.0,
        term_slope=0.02,
        regime=regime,
    )


def make_risk(tier=1, budget=1000.0, equity=100_000.0, used=0.0, portfolio=None) -> RiskAuthority:
    # Portfolio cap defaults to 3x the per-trade cap, mirroring the real tiers.
    portfolio_cap = portfolio if portfolio is not None else budget * 3
    return RiskAuthority(
        tier=tier,
        max_loss_pct=budget / equity,
        budget_dollars=budget,
        portfolio_pct=portfolio_cap / equity,
        portfolio_cap_dollars=portfolio_cap,
        used_dollars=used,
        closed_trades=3,
        breaches=0,
        drawdown_pct=0.5,
        equity=equity,
        next_promotion="Tier 2 (2.0% per trade) needs 3 more clean closed trades.",
    )


def contango() -> TermStructure:
    return TermStructure(
        symbol="SPY",
        points=[TermPoint(expiry=EXPIRY, dte=31, iv_atm=0.24)],
        near_iv=0.20,
        far_iv=0.26,
        near_dte=7,
        far_dte=60,
        slope=0.06,
    )


def backwardation() -> TermStructure:
    return TermStructure(
        symbol="SPY",
        points=[TermPoint(expiry=EXPIRY, dte=31, iv_atm=0.40)],
        near_iv=0.48,
        far_iv=0.34,
        near_dte=7,
        far_dte=60,
        slope=-0.14,
    )


_UNSET = object()


def make_ctx(term=_UNSET, earnings=_UNSET, risk=None, **kwargs) -> GateContext:
    # Sentinel rather than None: several tests need to pass term=None or
    # earnings=None *explicitly* to exercise the unknown-data paths.
    defaults = {
        "vol_state": make_vol_state(),
        "risk": risk or make_risk(),
        "realized_vol": 0.10,
        "term": contango() if term is _UNSET else term,
        "earnings": EarningsCalendar(data={}) if earnings is _UNSET else earnings,
        "as_of": AS_OF,
        "min_open_interest": 100,
        "max_spread_pct": 0.15,
    }
    defaults.update(kwargs)
    return GateContext(**defaults)


# ====================================================================
# Liquidity
# ====================================================================


def test_liquidity_passes_on_a_liquid_structure():
    r = liquidity_gate(make_candidate(), make_ctx())
    assert r.passed
    assert "Liquid" in r.reason and "5,000" in r.reason


def test_liquidity_fails_on_thin_open_interest():
    r = liquidity_gate(make_candidate(oi=12), make_ctx())
    assert not r.passed
    assert "12" in r.reason and "100" in r.reason
    assert r.detail["worst_open_interest"] == 12


def test_liquidity_fails_on_a_wide_spread():
    """$1.00 bid against $3.00 ask on a $2.00 mid — a 100% spread."""
    r = liquidity_gate(make_candidate(bid=1.00, ask=3.00), make_ctx())
    assert not r.passed
    assert "spread" in r.reason.lower()
    assert r.detail["worst_spread_pct"] > 0.15


def test_liquidity_fails_when_a_leg_has_no_bid():
    """A leg with no bid cannot be closed, so the risk is defined on paper only."""
    r = liquidity_gate(make_candidate(bid=0.0), make_ctx())
    assert not r.passed
    assert "No two-sided market" in r.reason
    assert r.detail["unquoted"]


def test_liquidity_respects_a_configured_volume_floor():
    ctx = make_ctx(min_volume=500)
    r = liquidity_gate(make_candidate(), ctx)
    assert not r.passed
    assert "volume" in r.reason.lower()


# ====================================================================
# Earnings
# ====================================================================


def test_earnings_skipped_for_an_etf():
    r = earnings_gate(make_candidate(symbol="SPY"), make_ctx())
    assert r.passed and r.skipped
    assert "ETF" in r.reason


def test_earnings_blocks_a_single_name_with_no_confirmed_date():
    """Unknown is not clear. Alpaca serves no earnings calendar, so an unknown
    date means the event window cannot be ruled out."""
    r = earnings_gate(make_candidate(symbol="NVDA"), make_ctx())
    assert not r.passed
    assert "No confirmed earnings date" in r.reason
    assert r.detail["status"] == "unknown"


def test_earnings_unknown_does_not_block_a_long_premium_structure():
    """Buying premium into an event is a different risk — paying for an IV
    crush, not being short it."""
    r = earnings_gate(make_candidate("CALL_DEBIT", symbol="NVDA"), make_ctx())
    assert r.passed


def test_earnings_unknown_can_be_configured_not_to_block():
    ctx = make_ctx(earnings_unknown_blocks=False)
    assert earnings_gate(make_candidate(symbol="NVDA"), ctx).passed


def test_earnings_blocks_inside_the_blackout_window():
    cal = EarningsCalendar(data={"NVDA": [date(2026, 9, 3)]})
    r = earnings_gate(make_candidate(symbol="NVDA"), make_ctx(earnings=cal))
    assert not r.passed
    assert "03 Sep" in r.reason
    assert "crush" in r.reason
    assert r.detail["days_away"] == 4


def test_earnings_blocks_a_report_before_expiry_even_outside_the_window():
    """Holding a short premium structure across a print is the same mistake as
    opening into one."""
    cal = EarningsCalendar(data={"NVDA": [date(2026, 9, 25)]})
    r = earnings_gate(make_candidate(symbol="NVDA"), make_ctx(earnings=cal))
    assert not r.passed
    assert "25 Sep" in r.reason


def test_earnings_passes_when_the_report_falls_after_expiry():
    cal = EarningsCalendar(data={"NVDA": [date(2026, 11, 20)]})
    r = earnings_gate(make_candidate(symbol="NVDA"), make_ctx(earnings=cal))
    assert r.passed
    assert "after expiry" in r.reason


def test_earnings_blocks_when_no_calendar_is_loaded_at_all():
    r = earnings_gate(make_candidate(symbol="NVDA"), make_ctx(earnings=None))
    assert not r.passed
    assert "cannot be ruled out" in r.reason


# ====================================================================
# Term structure — test this hard
# ====================================================================


@pytest.mark.parametrize("kind", ["PUT_CREDIT", "CALL_CREDIT"])
def test_backwardation_always_blocks_premium_selling(kind):
    """The single most important gate in the system.

    Selling volatility into an inverted curve is the standard way to blow up an
    options account, and no VRP is large enough to justify it.
    """
    r = term_structure_gate(make_candidate(kind), make_ctx(term=backwardation()))
    assert not r.passed
    assert "Backwardation" in r.reason
    assert "48.0" in r.reason and "34.0" in r.reason
    assert r.detail["shape"] == "backwardation"


def test_backwardation_blocks_an_iron_condor_too():
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
        as_of=AS_OF,
    )
    r = term_structure_gate(Candidate(structure=condor), make_ctx(term=backwardation()))
    assert not r.passed


def test_backwardation_does_not_block_buying_premium():
    """The rule is about selling into stress, not about refusing to act."""
    r = term_structure_gate(make_candidate("CALL_DEBIT"), make_ctx(term=backwardation()))
    assert r.passed and r.skipped


def test_term_gate_passes_in_contango():
    r = term_structure_gate(make_candidate(), make_ctx(term=contango()))
    assert r.passed
    assert "contango" in r.reason
    assert r.detail["shape"] == "contango"


def test_unknown_term_structure_blocks_premium_selling():
    """An unknown curve is not a flat one."""
    r = term_structure_gate(make_candidate(), make_ctx(term=None))
    assert not r.passed
    assert "could not be determined" in r.reason


def test_a_flat_curve_is_not_backwardation():
    """Quote noise on a single expiry must not read as market panic."""
    flat = contango().model_copy(update={"slope": 0.001, "near_iv": 0.24, "far_iv": 0.241})
    assert term_structure_gate(make_candidate(), make_ctx(term=flat)).passed


# ====================================================================
# Stress
# ====================================================================


def test_stress_passes_with_a_generous_budget():
    c = make_candidate()
    r = stress_gate(c, make_ctx(risk=make_risk(budget=10_000.0)))
    assert r.passed
    assert "Survives all 84 scenarios" in r.reason
    assert len(c.stress_grid) == 84
    assert c.worst_case < 0


def test_stress_fails_and_names_the_breaching_cell():
    """The detail must identify the correct cell so the UI can highlight it."""
    c = make_candidate()
    r = stress_gate(c, make_ctx(risk=make_risk(budget=100.0)))
    assert not r.passed
    assert r.detail["breached_count"] > 0
    assert r.detail["grid_size"] == 84

    cell = r.detail["worst_cell"]
    assert cell["price_shock"] in (-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0)
    assert cell["iv_shock"] in (0.7, 1.0, 1.5, 2.0)
    assert cell["time_point"] in ("NOW", "MID", "EXPIRY")

    # The named cell must actually be the worst one in the attached grid.
    worst = min(c.stress_grid, key=lambda x: x.pnl)
    assert worst.price_shock == cell["price_shock"]
    assert worst.iv_shock == cell["iv_shock"]
    assert worst.time_point == cell["time_point"]
    assert r.detail["worst_pnl"] == worst.pnl


def test_stress_reason_reads_as_human_copy():
    """This string is rendered verbatim in the UI and read aloud in the demo."""
    r = stress_gate(make_candidate(), make_ctx(risk=make_risk(budget=100.0)))
    assert r.reason.startswith("Worst case −$")
    assert "σ" in r.reason
    assert "exceeds the tier 1 per-trade budget of $100" in r.reason
    assert r.detail["failed_check"] == "absolute"


def test_a_verticals_worst_case_never_exceeds_its_max_loss():
    """A correction to docs/01-ARCHITECTURE.md §5, pinned as a test.

    A vertical's liability is bounded above by width × e^(−rT), strictly less
    than the width, so the mark-to-market loss can never exceed the terminal max
    loss however violent the shock. The spec's "you can be down far more than
    that along the way" is true of naked positions, not of these.

    This is why the stress gate needs the routine-move check to do real work.
    """
    c = make_candidate()
    for rv in (0.10, 0.35, 1.00):
        stress_gate(c, make_ctx(risk=make_risk(budget=10_000.0), realized_vol=rv))
        worst = min(cell.pnl for cell in c.stress_grid)
        assert worst >= -c.structure.max_loss - 0.01
        assert worst == pytest.approx(-c.structure.max_loss, abs=0.01)


def test_stress_catches_strikes_that_a_routine_move_already_reaches():
    """The check that max loss alone cannot make.

    Max loss $420 sits comfortably inside a $700 budget, so the budget gate
    would wave this through. But spot is 590 against a 580 short strike — well
    under one sigma at 35% realized vol — so an ordinary move already takes most
    of the loss. The grid is the only thing that can see that.
    """
    c = make_candidate()
    ctx = make_ctx(risk=make_risk(budget=10_000.0), realized_vol=0.35)
    assert c.structure.max_loss < ctx.risk.budget_dollars, "budget gate alone would pass this"

    r = stress_gate(c, ctx)
    assert not r.passed, "a 1σ move reaching most of the max loss must be refused"
    assert r.detail["failed_check"] == "routine_move"
    assert "too close to the money" in r.reason
    assert "The max loss fits the budget; the path to it is too easy." in r.reason


def test_stress_passes_when_the_strikes_are_far_enough_out():
    """The mirror case: same structure, a calm underlying, and it passes."""
    c = make_candidate()
    r = stress_gate(c, make_ctx(risk=make_risk(budget=10_000.0), realized_vol=0.03))
    assert r.passed
    assert "Survives all 84 scenarios" in r.reason


def test_stress_fails_on_a_zero_budget():
    r = stress_gate(make_candidate(), make_ctx(risk=make_risk(budget=0.0)))
    assert not r.passed
    assert "no room" in r.reason


# ====================================================================
# Budget
# ====================================================================


def test_budget_passes_when_max_loss_fits_the_tier():
    r = budget_gate(make_candidate(), make_ctx(risk=make_risk(tier=1, budget=1000.0)))
    assert r.passed
    assert "42%" in r.reason  # 420 / 1000
    assert "portfolio cap" in r.reason


def test_budget_respects_the_current_tier():
    """Same structure, different tiers: $420 fits tier 1 but not tier 0."""
    candidate = make_candidate()
    tier0 = make_risk(tier=0, budget=500.0)
    tier0.budget_dollars = 400.0  # 0.4% of a $100k account — below the max loss
    assert not budget_gate(candidate, make_ctx(risk=tier0)).passed
    assert budget_gate(candidate, make_ctx(risk=make_risk(tier=1, budget=1000.0))).passed


def test_one_open_position_does_not_lock_the_desk_out():
    """The lockout bug, pinned as the spec's acceptance case.

    One $341 position open at tier 0 (per-trade $500, portfolio $1,500): a
    $412 candidate must PASS. Under the old conflated model "available" read
    $159 and everything was refused forever.
    """
    risk = make_risk(tier=0, budget=500.0, used=341.0, portfolio=1500.0)
    candidate = make_candidate()
    candidate.structure = candidate.structure.model_copy(update={"max_loss": 412.0})
    r = budget_gate(candidate, make_ctx(risk=risk))
    assert r.passed, r.reason
    assert r.detail["proposed_total"] == pytest.approx(753.0)


def test_budget_fails_on_the_portfolio_cap_and_names_it():
    """$800 committed + $420 proposed = $1,220 > a $1,000 portfolio cap —
    refused, even though $420 fits the per-trade cap comfortably."""
    risk = make_risk(tier=1, budget=1000.0, used=800.0, portfolio=1000.0)
    r = budget_gate(make_candidate(), make_ctx(risk=risk))
    assert not r.passed
    assert r.detail["failed_check"] == "portfolio"
    assert "Portfolio cap" in r.reason
    assert "per-trade cap" in r.reason  # copy says the OTHER check was fine
    assert r.detail["proposed_total"] == pytest.approx(1220.0)


def test_budget_per_trade_failure_names_itself():
    risk = make_risk(tier=0, budget=300.0)
    r = budget_gate(make_candidate(), make_ctx(risk=risk))
    assert not r.passed
    assert r.detail["failed_check"] == "per_trade"
    assert "Per-trade cap" in r.reason


def test_budget_fails_at_the_concurrent_position_cap():
    ctx = make_ctx(open_positions=3, max_concurrent_positions=3)
    r = budget_gate(make_candidate(), ctx)
    assert not r.passed
    assert "Capacity, not conviction" in r.reason


def test_budget_failure_tells_the_operator_what_would_change_it():
    risk = make_risk(tier=0, budget=300.0)
    r = budget_gate(make_candidate(), make_ctx(risk=risk))
    assert not r.passed
    assert "Tier 2" in r.reason or "Tier 1" in r.reason


def test_capacity_failure_names_itself():
    ctx = make_ctx(open_positions=3, max_concurrent_positions=3)
    r = budget_gate(make_candidate(), ctx)
    assert not r.passed
    assert r.detail["failed_check"] == "capacity"


# ====================================================================
# The chain runner
# ====================================================================


def test_chain_evaluates_every_gate_even_after_one_fails():
    """A product decision, not an implementation detail: the UI shows the full
    picture of why a trade was refused, not just the first thing wrong."""
    c = run_gates(make_candidate(oi=1), make_ctx(term=backwardation()))
    assert len(c.gates) == len(default_gates()) == 5
    assert [g.gate for g in c.gates] == ["liquidity", "earnings", "term", "stress", "budget"]
    assert len(c.failed_gates) >= 2
    assert not c.passed_all


def test_chain_passes_a_clean_candidate():
    c = run_gates(make_candidate(), make_ctx(risk=make_risk(budget=10_000.0)))
    assert c.passed_all
    assert all(g.passed for g in c.gates)
    assert summarise(c) == "passed all gates"


def test_a_gate_that_raises_is_a_failure_not_a_pass():
    """A risk check that errors is not a risk check that passed."""

    def exploding_gate(_candidate, _ctx):
        raise RuntimeError("upstream data vanished")

    exploding_gate.gate_name = "exploding"
    c = run_gates(make_candidate(), make_ctx(), gates=[exploding_gate])
    assert not c.passed_all
    assert c.gates[0].passed is False
    assert "upstream data vanished" in c.gates[0].reason
    assert c.gates[0].detail["exception"] == "RuntimeError"


def test_skipped_gates_do_not_block():
    c = run_gates(make_candidate("CALL_DEBIT"), make_ctx(risk=make_risk(budget=10_000.0)))
    skipped = [g for g in c.gates if g.skipped]
    assert skipped, "the term gate should be skipped for a long-premium structure"
    assert c.passed_all


def test_summarise_names_every_failing_gate():
    c = run_gates(make_candidate(oi=1), make_ctx(term=backwardation()))
    text = summarise(c)
    assert "failed" in text
    assert "liquidity" in text and "term" in text


def test_every_gate_reason_is_written_for_a_human():
    """Reasons render verbatim in the UI. They must carry numbers, not codes."""
    for candidate, ctx in [
        (make_candidate(), make_ctx(risk=make_risk(budget=10_000.0))),
        (make_candidate(oi=1), make_ctx(term=backwardation(), risk=make_risk(budget=50.0))),
    ]:
        for gate in run_gates(candidate, ctx).gates:
            assert isinstance(gate.reason, str)
            assert len(gate.reason) > 25, f"{gate.gate}: {gate.reason!r} is too terse for the UI"
            assert gate.reason[0].isupper() or gate.reason.startswith("$")
            assert not gate.reason.isupper(), "reasons are copy, not error codes"


def test_gate_result_defaults_are_safe():
    r = GateResult(gate="x", passed=False, reason="because")
    assert r.detail == {}
    assert r.skipped is False


def test_the_routine_check_asks_the_opposite_question_of_a_debit_spread():
    """A debit spread's max loss IS the premium paid.

    An adverse move of any size takes 80–100% of it at every level of realized
    volatility — that is the structure working as designed, not a defect. Applying
    the short-premium test here would refuse every debit spread ever built and
    make the whole BUY_VOL regime untradeable.
    """
    from skew.stress.scenarios import build_grid, worst_within

    # An at-the-money debit spread — the shape the BUY_VOL regime actually builds.
    atm_debit = assemble(
        "SPY",
        "CALL_DEBIT",
        [_leg(590, "BUY", "CALL", 12.00), _leg(600, "SELL", "CALL", 7.00)],
        spot=590.0,
        as_of=AS_OF,
    )
    for rv in (0.15, 0.25, 0.50):
        grid = build_grid(atm_debit, realized_vol=rv, budget=100_000.0)
        routine = worst_within(grid, 1.0)
        assert abs(routine.pnl) > 0.6 * atm_debit.max_loss, (
            f"at rv={rv} a routine adverse move should take most of the premium; "
            f"got {routine.pnl:.2f} of {atm_debit.max_loss:.2f}"
        )

    debit = make_candidate("CALL_DEBIT")

    # And yet it must still pass, because the question asked of it is different.
    r = stress_gate(debit, make_ctx(risk=make_risk(budget=10_000.0), realized_vol=0.25))
    assert r.passed, r.reason
    assert r.detail["short_premium"] is False
    assert "breakeven sits" in r.reason


def test_a_debit_spread_whose_breakeven_needs_a_tail_event_is_refused():
    """The honest mirror for long premium: how far must price actually travel?

    Measured on the breakeven rather than on the grid, because a long-vega
    structure profits from an IV shock alone — which would mask a strike that
    price realistically cannot reach.
    """
    debit = make_candidate("CALL_DEBIT")
    # Barely any realized volatility, so the breakeven is many sigma away.
    r = stress_gate(debit, make_ctx(risk=make_risk(budget=10_000.0), realized_vol=0.01))
    assert not r.passed
    assert r.detail["failed_check"] == "breakeven_too_far"
    assert "lottery ticket" in r.reason
    assert r.detail["breakeven_sigma"] > 1.25
