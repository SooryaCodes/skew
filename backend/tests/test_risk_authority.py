"""The earned risk tier state machine.

docs/07-TESTING.md lists tier promotion and demotion transitions as required.
The narrative — an agent that earns the right to size up — only means anything
if the transitions are actually mechanical, so they are pinned here.
"""

from __future__ import annotations

import pytest

from skew.risk.authority import (
    DEMOTION_DRAWDOWN_PCT,
    MAX_TIER,
    TIERS,
    current_drawdown,
    evaluate_tier,
    get_authority,
    record_breach,
    record_closed_trade,
    record_equity,
    reset_state,
)

EQUITY = 100_000.0


@pytest.fixture(autouse=True)
def _clean_state():
    reset_state()
    yield


# ------------------------------------------------------------------ tiers


def test_tier_table_matches_the_architecture_doc():
    """Tier 0: 0.5%. Tier 1: 1.0% after 3 clean trades. Tier 2: 2.0% after 6."""
    assert TIERS[0].max_loss_pct == 0.005
    assert TIERS[1].max_loss_pct == 0.010
    assert TIERS[2].max_loss_pct == 0.020
    assert TIERS[1].trades_required == 3
    assert TIERS[2].trades_required == 6
    assert MAX_TIER == 2


def test_starts_at_tier_zero_with_half_a_percent():
    a = get_authority(EQUITY)
    assert a.tier == 0
    assert a.max_loss_pct == 0.005
    assert a.budget_dollars == pytest.approx(500.0)
    assert a.closed_trades == 0 and a.breaches == 0


def test_budget_scales_with_equity():
    assert get_authority(50_000.0).budget_dollars == pytest.approx(250.0)
    assert get_authority(200_000.0).budget_dollars == pytest.approx(1_000.0)


# ------------------------------------------------------------------ promotion


def test_promotes_to_tier_one_after_three_clean_trades():
    for _ in range(2):
        record_closed_trade(clean=True)
    assert evaluate_tier(EQUITY) == 0, "two trades is not enough"

    record_closed_trade(clean=True)
    assert evaluate_tier(EQUITY) == 1
    assert get_authority(EQUITY).budget_dollars == pytest.approx(1_000.0)


def test_promotes_to_tier_two_after_six_clean_trades():
    for _ in range(6):
        record_closed_trade(clean=True)
    assert evaluate_tier(EQUITY) == 2
    assert get_authority(EQUITY).budget_dollars == pytest.approx(2_000.0)


def test_does_not_promote_beyond_the_top_tier():
    for _ in range(50):
        record_closed_trade(clean=True)
    assert evaluate_tier(EQUITY) == MAX_TIER


# ------------------------------------------------------------------ demotion


def test_a_breach_demotes_to_tier_zero_not_one_step_down():
    """The authority was granted on a clean record; a breach ends that record."""
    for _ in range(6):
        record_closed_trade(clean=True)
    assert evaluate_tier(EQUITY) == 2

    assert record_breach("stress gate breached on an open position") == 0
    assert evaluate_tier(EQUITY) == 0
    assert get_authority(EQUITY).budget_dollars == pytest.approx(500.0)


def test_a_breach_is_not_forgiven_by_more_clean_trades():
    """ "Wait long enough and it does not count" is not a risk policy."""
    record_breach("breach")
    for _ in range(20):
        record_closed_trade(clean=True)
    assert evaluate_tier(EQUITY) == 0

    a = get_authority(EQUITY)
    assert a.breaches == 1
    assert "not restored by time" in a.next_promotion


def test_closing_a_trade_on_a_breach_demotes():
    for _ in range(6):
        record_closed_trade(clean=True)
    assert evaluate_tier(EQUITY) == 2
    record_closed_trade(clean=False)
    assert evaluate_tier(EQUITY) == 0


def test_drawdown_caps_the_tier():
    """Above the drawdown limit, tier 2 is not available whatever the count."""
    for _ in range(6):
        record_closed_trade(clean=True)
    record_equity(EQUITY)
    assert evaluate_tier(EQUITY) == 2

    # 5% below the high-water mark.
    drawn = EQUITY * 0.95
    assert current_drawdown(drawn) == pytest.approx(5.0, abs=0.01)
    assert current_drawdown(drawn) > DEMOTION_DRAWDOWN_PCT
    assert evaluate_tier(drawn) == 1


def test_recovering_from_drawdown_restores_the_tier():
    for _ in range(6):
        record_closed_trade(clean=True)
    record_equity(EQUITY)
    assert evaluate_tier(EQUITY * 0.95) == 1
    assert evaluate_tier(EQUITY) == 2, "a clean record recovers when the drawdown does"


# ------------------------------------------------------------------ drawdown


def test_drawdown_tracks_the_high_water_mark():
    record_equity(100_000.0)
    record_equity(110_000.0)
    record_equity(105_000.0)
    assert current_drawdown(105_000.0) == pytest.approx(100 * 5_000 / 110_000, abs=0.01)


def test_drawdown_is_never_negative():
    record_equity(100_000.0)
    assert current_drawdown(120_000.0) == 0.0


def test_non_positive_equity_is_refused():
    record_equity(-5.0)
    record_equity(0.0)
    assert current_drawdown(100_000.0) == 0.0


# ------------------------------------------------------------------ copy


def test_next_promotion_copy_tells_the_operator_what_it_takes():
    assert "3 more clean closed trades" in get_authority(EQUITY).next_promotion

    record_closed_trade(clean=True)
    assert "2 more clean closed trades" in get_authority(EQUITY).next_promotion

    for _ in range(5):
        record_closed_trade(clean=True)
    assert "Top tier" in get_authority(EQUITY).next_promotion


def test_authority_reports_available_budget_after_commitments():
    a = get_authority(EQUITY, used_dollars=300.0, open_positions=1)
    assert a.budget_dollars == pytest.approx(500.0)
    assert a.used_dollars == pytest.approx(300.0)
    assert a.available_dollars == pytest.approx(200.0)
    assert a.open_positions == 1


def test_available_never_goes_negative():
    a = get_authority(EQUITY, used_dollars=900.0)
    assert a.available_dollars == 0.0


def test_evaluate_tier_is_idempotent():
    for _ in range(3):
        record_closed_trade(clean=True)
    assert evaluate_tier(EQUITY) == evaluate_tier(EQUITY) == evaluate_tier(EQUITY) == 1


def test_state_survives_a_fresh_read():
    """Persisted, not held in memory — a tier that reset on deploy is decorative."""
    for _ in range(3):
        record_closed_trade(clean=True)
    evaluate_tier(EQUITY)
    assert get_authority(EQUITY).tier == 1
    assert get_authority(EQUITY).closed_trades == 3
