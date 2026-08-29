"""Market hours, expirations, and earnings dates.

Two of these three come from Alpaca. The third does not, and that is worth
stating plainly rather than papering over:

**Alpaca serves no earnings calendar.** There is a corporate-actions endpoint,
but it covers dividends and splits, not earnings dates. So the earnings gate
reads from an operator-maintained file, ``backend/data/earnings.json``, and when
a single-name symbol has no entry the gate **blocks** rather than waving the
trade through. Selling premium into an unknown event window is precisely the
mistake the desk exists to avoid, and "if market data is missing, abstain
loudly" is the house rule. ETFs are exempt because they genuinely do not report.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

EASTERN = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
EARNINGS_FILE = DATA_DIR / "earnings.json"

# Index and sector ETFs do not report earnings. Anything not on this list is
# treated as a single name and must have a known earnings date.
KNOWN_ETFS: frozenset[str] = frozenset(
    {
        "SPY",
        "QQQ",
        "IWM",
        "DIA",
        "VTI",
        "VOO",
        "EFA",
        "EEM",
        "TLT",
        "IEF",
        "HYG",
        "LQD",
        "GLD",
        "SLV",
        "USO",
        "UNG",
        "XLE",
        "XLF",
        "XLK",
        "XLV",
        "XLI",
        "XLP",
        "XLU",
        "XLY",
        "XLB",
        "XLRE",
        "XLC",
        "SMH",
        "ARKK",
        "VXX",
        "UVXY",
        "SQQQ",
        "TQQQ",
        "IVV",
        "RSP",
        "MDY",
    }
)

# US market holidays through the project window. Alpaca's calendar endpoint is
# authoritative when credentials exist; this is the offline fallback so the
# market-hours check still works in tests and without a network.
_STATIC_HOLIDAYS: frozenset[date] = frozenset(
    {
        date(2025, 1, 1),
        date(2025, 1, 9),
        date(2025, 1, 20),
        date(2025, 2, 17),
        date(2025, 4, 18),
        date(2025, 5, 26),
        date(2025, 6, 19),
        date(2025, 7, 4),
        date(2025, 9, 1),
        date(2025, 11, 27),
        date(2025, 12, 25),
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
    }
)


# ----------------------------------------------------------------------
# Market hours — pure functions
# ----------------------------------------------------------------------


def to_eastern(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(EASTERN)


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in _STATIC_HOLIDAYS


def is_regular_session(moment: datetime | None = None) -> bool:
    """True during the 09:30–16:00 Eastern regular session on a trading day.

    Offline fallback. When credentials exist, ``MarketCalendar.is_open`` prefers
    Alpaca's clock, which knows about early closes this function does not.
    """
    eastern = to_eastern(moment or datetime.now(UTC))
    if not is_trading_day(eastern.date()):
        return False
    return REGULAR_OPEN <= eastern.time() < REGULAR_CLOSE


def minutes_to_close(moment: datetime | None = None) -> int:
    """Minutes remaining in the regular session; 0 when closed."""
    eastern = to_eastern(moment or datetime.now(UTC))
    if not is_regular_session(eastern):
        return 0
    close = eastern.replace(hour=16, minute=0, second=0, microsecond=0)
    return max(0, int((close - eastern).total_seconds() // 60))


def next_session_open(moment: datetime | None = None) -> datetime:
    eastern = to_eastern(moment or datetime.now(UTC))
    day = eastern.date()
    if eastern.time() >= REGULAR_CLOSE or not is_trading_day(day):
        day += timedelta(days=1)
    while not is_trading_day(day):
        day += timedelta(days=1)
    return datetime.combine(day, REGULAR_OPEN, tzinfo=EASTERN)


# ----------------------------------------------------------------------
# Expiration selection — pure
# ----------------------------------------------------------------------


def dte(expiry: date, as_of: date | None = None) -> int:
    return (expiry - (as_of or datetime.now(UTC).date())).days


def select_expiries(
    expiries: list[date],
    dte_min: int,
    dte_max: int,
    as_of: date | None = None,
) -> list[date]:
    """Expiries inside the target DTE band, nearest first."""
    ref = as_of or datetime.now(UTC).date()
    inside = [e for e in expiries if dte_min <= (e - ref).days <= dte_max]
    return sorted(inside)


def third_friday(year: int, month: int) -> date:
    """The monthly expiration. Useful for preferring liquid standard expiries."""
    first = date(year, month, 1)
    offset = (4 - first.weekday()) % 7  # 4 = Friday
    return first + timedelta(days=offset + 14)


def is_monthly_expiry(expiry: date) -> bool:
    return expiry == third_friday(expiry.year, expiry.month)


# ----------------------------------------------------------------------
# Earnings
# ----------------------------------------------------------------------


class EarningsCalendar:
    """Operator-maintained earnings dates.

    File shape (``backend/data/earnings.json``)::

        {
          "_comment": "...",
          "symbols": { "AAPL": ["2025-10-30"], "NVDA": ["2025-11-19"] }
        }

    ``status_for`` returns one of ``"etf"``, ``"known"`` or ``"unknown"`` so the
    gate can write an honest reason string for each case.
    """

    def __init__(self, path: Path | None = None, data: dict[str, list[date]] | None = None) -> None:
        self.path = path or EARNINGS_FILE
        self._dates: dict[str, list[date]] = data if data is not None else self._load()

    def _load(self) -> dict[str, list[date]]:
        if not self.path.exists():
            log.warning(
                "No earnings file at %s — single-name symbols will be blocked by the "
                "earnings gate until it is populated.",
                self.path,
            )
            return {}
        try:
            raw: dict[str, Any] = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            log.exception("Could not read earnings file %s", self.path)
            return {}

        out: dict[str, list[date]] = {}
        for symbol, entries in (raw.get("symbols") or {}).items():
            parsed: list[date] = []
            for entry in entries or []:
                try:
                    parsed.append(date.fromisoformat(str(entry)[:10]))
                except ValueError:
                    log.warning("Ignoring unparseable earnings date %r for %s", entry, symbol)
            out[symbol.upper()] = sorted(parsed)
        return out

    def status_for(self, symbol: str) -> str:
        key = symbol.upper()
        if key in KNOWN_ETFS:
            return "etf"
        return "known" if self._dates.get(key) else "unknown"

    def dates_for(self, symbol: str) -> list[date]:
        return list(self._dates.get(symbol.upper(), []))

    def next_earnings(self, symbol: str, as_of: date | None = None) -> date | None:
        ref = as_of or datetime.now(UTC).date()
        upcoming = [d for d in self.dates_for(symbol) if d >= ref]
        return upcoming[0] if upcoming else None

    def days_to_earnings(self, symbol: str, as_of: date | None = None) -> int | None:
        nxt = self.next_earnings(symbol, as_of)
        if nxt is None:
            return None
        return (nxt - (as_of or datetime.now(UTC).date())).days

    def in_window(
        self,
        symbol: str,
        window_days: int,
        as_of: date | None = None,
        through: date | None = None,
    ) -> date | None:
        """The earnings date that falls inside the blackout, or None.

        The window runs from ``window_days`` before the report through
        ``window_days`` after it, and also catches any report scheduled between
        now and ``through`` (the position's expiry) — holding a short premium
        structure across an earnings print is the same mistake as opening into
        one.
        """
        ref = as_of or datetime.now(UTC).date()
        horizon = through or (ref + timedelta(days=window_days))
        for d in self.dates_for(symbol):
            if abs((d - ref).days) <= window_days:
                return d
            if ref <= d <= horizon:
                return d
        return None


class MarketCalendar:
    """Market hours, preferring Alpaca's clock and falling back to static rules."""

    def __init__(self, broker: Any | None = None) -> None:
        self._broker = broker

    def is_open(self, moment: datetime | None = None) -> bool:
        if self._broker is not None and getattr(self._broker, "available", False):
            try:
                return bool(self._broker.is_market_open())
            except Exception as exc:  # noqa: BLE001 — a dead clock must not stop the loop
                log.warning("Alpaca clock unavailable, falling back to static hours: %s", exc)
        return is_regular_session(moment)

    def minutes_to_close(self, moment: datetime | None = None) -> int:
        return minutes_to_close(moment)

    def next_open(self, moment: datetime | None = None) -> datetime:
        return next_session_open(moment)
