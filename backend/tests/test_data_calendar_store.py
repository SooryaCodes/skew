"""Market hours, expiry selection, the earnings file, and the IV snapshot store."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from skew.data.bars import parse_bars
from skew.data.calendar import (
    EASTERN,
    EarningsCalendar,
    MarketCalendar,
    is_monthly_expiry,
    is_regular_session,
    is_trading_day,
    minutes_to_close,
    next_session_open,
    select_expiries,
    third_friday,
)
from skew.data.store import (
    daily_closing_iv,
    history_window_days,
    iv_series,
    observation_count,
    record_iv,
)

# ------------------------------------------------------------------ hours


def _eastern(y, m, d, hh, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=EASTERN)


@pytest.mark.parametrize(
    ("moment", "open_"),
    [
        (_eastern(2026, 8, 27, 10, 0), True),  # Thursday mid-session
        (_eastern(2026, 8, 27, 9, 30), True),  # exactly the open — inclusive
        (_eastern(2026, 8, 27, 15, 59), True),
        (_eastern(2026, 8, 27, 16, 0), False),  # exactly the close — exclusive
        (_eastern(2026, 8, 27, 9, 29), False),  # one minute early
        (_eastern(2026, 8, 29, 12, 0), False),  # Saturday
        (_eastern(2026, 8, 30, 12, 0), False),  # Sunday
        (_eastern(2026, 7, 3, 12, 0), False),  # Independence Day observed
        (_eastern(2026, 12, 25, 12, 0), False),  # Christmas
    ],
)
def test_regular_session_boundaries(moment, open_):
    assert is_regular_session(moment) is open_


def test_utc_input_is_converted_to_eastern():
    """14:00 UTC is 10:00 Eastern in summer — inside the session."""
    assert is_regular_session(datetime(2026, 8, 27, 14, 0, tzinfo=UTC)) is True
    # 02:00 UTC is 22:00 the previous Eastern evening — closed.
    assert is_regular_session(datetime(2026, 8, 27, 2, 0, tzinfo=UTC)) is False


def test_naive_datetimes_are_treated_as_utc():
    assert is_regular_session(datetime(2026, 8, 27, 14, 0)) is True


def test_minutes_to_close():
    assert minutes_to_close(_eastern(2026, 8, 27, 15, 30)) == 30
    assert minutes_to_close(_eastern(2026, 8, 27, 9, 30)) == 390
    assert minutes_to_close(_eastern(2026, 8, 29, 12, 0)) == 0  # weekend


def test_next_session_open_skips_the_weekend():
    nxt = next_session_open(_eastern(2026, 8, 28, 17, 0))  # Friday evening
    assert nxt.date() == date(2026, 8, 31)  # Monday
    assert nxt.hour == 9 and nxt.minute == 30


def test_holidays_are_not_trading_days():
    assert not is_trading_day(date(2026, 12, 25))
    assert not is_trading_day(date(2026, 1, 1))
    assert is_trading_day(date(2026, 8, 27))


def test_market_calendar_falls_back_when_broker_unavailable():
    class NoBroker:
        available = False

    cal = MarketCalendar(NoBroker())
    assert cal.is_open(_eastern(2026, 8, 27, 10, 0)) is True


def test_market_calendar_falls_back_when_the_clock_raises():
    class BadBroker:
        available = True

        def is_market_open(self):
            raise RuntimeError("clock endpoint down")

    # Must degrade to static hours, not propagate. A dead clock endpoint should
    # not take the whole loop down.
    assert MarketCalendar(BadBroker()).is_open(_eastern(2026, 8, 27, 10, 0)) is True


# ------------------------------------------------------------------ expiries


def test_third_friday_and_monthly_detection():
    assert third_friday(2026, 9) == date(2026, 9, 18)
    assert third_friday(2026, 1) == date(2026, 1, 16)
    assert is_monthly_expiry(date(2026, 9, 18))
    assert not is_monthly_expiry(date(2026, 9, 25))


def test_select_expiries_filters_to_the_dte_band():
    today = date(2026, 8, 30)
    expiries = [today + timedelta(days=d) for d in (1, 7, 20, 21, 30, 45, 46, 90)]
    chosen = select_expiries(expiries, 21, 45, as_of=today)
    assert [(e - today).days for e in chosen] == [21, 30, 45]


# ------------------------------------------------------------------ earnings


def test_etfs_are_exempt_from_earnings():
    cal = EarningsCalendar(data={})
    for etf in ("SPY", "QQQ", "IWM"):
        assert cal.status_for(etf) == "etf"
        assert cal.in_window(etf, 7, as_of=date(2026, 8, 30)) is None


def test_unknown_single_name_is_reported_as_unknown():
    """Not 'clear' — unknown. The gate treats the difference as decisive."""
    assert EarningsCalendar(data={}).status_for("NVDA") == "unknown"


def test_earnings_blackout_window_either_side_of_the_report():
    cal = EarningsCalendar(data={"AAPL": [date(2026, 9, 5)]})
    assert cal.status_for("AAPL") == "known"

    # Six days before — inside a 7-day window.
    assert cal.in_window("AAPL", 7, as_of=date(2026, 8, 30)) == date(2026, 9, 5)
    # Three days after — still inside.
    assert cal.in_window("AAPL", 7, as_of=date(2026, 9, 8)) == date(2026, 9, 5)
    # Three weeks before, with a short horizon — outside.
    assert cal.in_window("AAPL", 7, as_of=date(2026, 8, 10), through=date(2026, 8, 20)) is None


def test_earnings_between_now_and_expiry_blocks_even_outside_the_window():
    """Holding a short premium structure across a print is the same mistake as
    opening into one."""
    cal = EarningsCalendar(data={"AAPL": [date(2026, 10, 1)]})
    as_of = date(2026, 8, 30)
    assert cal.in_window("AAPL", 7, as_of=as_of) is None
    assert cal.in_window("AAPL", 7, as_of=as_of, through=date(2026, 10, 16)) == date(2026, 10, 1)


def test_days_to_earnings():
    cal = EarningsCalendar(data={"AAPL": [date(2026, 9, 5)]})
    assert cal.days_to_earnings("AAPL", as_of=date(2026, 8, 30)) == 6
    assert cal.days_to_earnings("NVDA", as_of=date(2026, 8, 30)) is None


def test_earnings_file_loads_and_tolerates_bad_dates(tmp_path):
    path = tmp_path / "earnings.json"
    path.write_text(json.dumps({"symbols": {"aapl": ["2026-09-05", "not-a-date"]}}))
    cal = EarningsCalendar(path=path)
    assert cal.dates_for("AAPL") == [date(2026, 9, 5)]


def test_missing_earnings_file_degrades_to_unknown_not_to_clear(tmp_path):
    cal = EarningsCalendar(path=tmp_path / "nope.json")
    assert cal.status_for("NVDA") == "unknown"


def test_shipped_earnings_file_parses():
    """The file committed to the repo must at least be valid JSON."""
    assert isinstance(EarningsCalendar().dates_for("AAPL"), list)


# ------------------------------------------------------------------ bars


def test_parse_bars_sorts_dedupes_and_drops_bad_rows():
    rows = [
        {"date": "2026-01-05", "open": 10, "high": 11, "low": 9, "close": 10.5},
        {"date": "2026-01-02", "open": 10, "high": 11, "low": 9, "close": 10.0},
        {"date": "2026-01-05", "open": 10, "high": 11, "low": 9, "close": 10.7},  # dup
        {"date": "2026-01-06", "open": 10, "high": 8, "low": 9, "close": 10.0},  # high < low
        {"date": "2026-01-07", "open": 10, "high": 11, "low": 9, "close": 0.0},  # bad close
    ]
    series = parse_bars("TEST", rows)
    assert [b.date for b in series.bars] == [date(2026, 1, 2), date(2026, 1, 5)]
    assert series.bars[1].close == 10.7, "last observation for a duplicated day wins"
    assert series.last_close == 10.7


def test_parse_bars_accepts_iso_strings_and_date_objects():
    rows = [
        {"date": date(2026, 1, 2), "open": 1, "high": 2, "low": 1, "close": 1.5},
        {"date": "2026-01-05T00:00:00Z", "open": 1, "high": 2, "low": 1, "close": 1.6},
    ]
    assert len(parse_bars("TEST", rows)) == 2


# ------------------------------------------------------------------ IV store


def test_record_and_read_back_iv_history():
    base = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)
    for i in range(5):
        assert record_iv("SPY", atm_iv=0.15 + i * 0.01, spot=700 + i, ts=base + timedelta(days=i))

    assert observation_count("SPY") == 5
    assert iv_series("SPY") == pytest.approx([0.15, 0.16, 0.17, 0.18, 0.19])
    assert history_window_days("SPY") == 4


def test_store_refuses_a_non_positive_iv():
    """A zero IV means the chain parse failed. Storing it poisons every rank
    computed afterwards."""
    assert record_iv("SPY", atm_iv=0.0) is False
    assert record_iv("SPY", atm_iv=-0.2) is False
    assert observation_count("SPY") == 0


def test_history_window_is_zero_for_an_unseen_symbol():
    assert history_window_days("ZZZZ") == 0
    assert observation_count("ZZZZ") == 0
    assert iv_series("ZZZZ") == []


def test_daily_closing_iv_keeps_the_last_sample_per_day():
    day = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)
    record_iv("QQQ", atm_iv=0.20, ts=day)
    record_iv("QQQ", atm_iv=0.22, ts=day + timedelta(hours=1))
    record_iv("QQQ", atm_iv=0.25, ts=day + timedelta(days=1))

    series = daily_closing_iv("QQQ")
    assert series == [("2026-08-20", 0.22), ("2026-08-21", 0.25)]
