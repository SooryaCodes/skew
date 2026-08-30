"""ATM implied-volatility snapshot persistence.

This module exists because of the trap in docs/01-ARCHITECTURE.md §4: **Alpaca
serves no historical implied volatility.** There is no endpoint. A 252-day IV
rank is not computable from this API, and any code claiming one is lying.

Option B from that section is implemented here — build the history forward from
the moment we start. Every few minutes we append ``(symbol, ts, atm_iv)`` to
SQLite. By demo day there are several days of genuine observations, which is
enough to render a real chart and to show the mechanism working.

The window length travels with the number everywhere it goes, so the UI can say
"IV rank over 5 days" rather than dressing five days up as a year.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from skew.audit.models import IVSnapshotRow
from skew.db import session_scope

log = logging.getLogger(__name__)

# Below this many observations an IV rank is noise, and we report None instead.
MIN_OBSERVATIONS_FOR_RANK = 24


class IVHistoryPoint:
    """A single stored observation. Deliberately plain — this is a hot read path."""

    __slots__ = ("atm_iv", "spot", "symbol", "term_slope", "ts")

    def __init__(
        self, symbol: str, ts: datetime, atm_iv: float, spot: float = 0.0, term_slope: float = 0.0
    ) -> None:
        self.symbol = symbol
        self.ts = ts
        self.atm_iv = atm_iv
        self.spot = spot
        self.term_slope = term_slope

    def as_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "ts": self.ts.isoformat(),
            "atm_iv": self.atm_iv,
            "spot": self.spot,
            "term_slope": self.term_slope,
        }


def record_iv(
    symbol: str,
    atm_iv: float,
    spot: float = 0.0,
    dte: int = 0,
    term_slope: float = 0.0,
    ts: datetime | None = None,
) -> bool:
    """Append one ATM IV observation. Returns False when the value is unusable.

    A zero or negative IV means the chain parse failed. Storing it would poison
    every rank computed afterwards, so it is refused and logged.
    """
    if atm_iv is None or atm_iv <= 0:
        log.warning("Refusing to store non-positive ATM IV %r for %s", atm_iv, symbol)
        return False

    with session_scope() as session:
        session.add(
            IVSnapshotRow(
                symbol=symbol.upper(),
                ts=ts or datetime.now(UTC),
                atm_iv=float(atm_iv),
                spot=float(spot or 0.0),
                dte=int(dte or 0),
                term_slope=float(term_slope or 0.0),
            )
        )
    return True


def iv_history(symbol: str, days: int = 365, limit: int = 5000) -> list[IVHistoryPoint]:
    """Stored observations for one symbol, oldest first."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    with session_scope() as session:
        rows = session.scalars(
            select(IVSnapshotRow)
            .where(IVSnapshotRow.symbol == symbol.upper(), IVSnapshotRow.ts >= cutoff)
            .order_by(IVSnapshotRow.ts.asc())
            .limit(limit)
        ).all()
    return [IVHistoryPoint(r.symbol, _aware(r.ts), r.atm_iv, r.spot, r.term_slope) for r in rows]


def iv_series(symbol: str, days: int = 365) -> list[float]:
    return [p.atm_iv for p in iv_history(symbol, days=days)]


def history_window_days(symbol: str) -> int:
    """How many days of IV history we actually hold for this symbol.

    This number is rendered next to every IV rank in the UI. It is the honest
    label that keeps the rank from being a lie.
    """
    with session_scope() as session:
        row = session.execute(
            select(func.min(IVSnapshotRow.ts), func.max(IVSnapshotRow.ts)).where(
                IVSnapshotRow.symbol == symbol.upper()
            )
        ).one()
    first, last = row
    if first is None or last is None:
        return 0
    return max(0, (_aware(last) - _aware(first)).days)


def distinct_history_days(symbol: str) -> int:
    """Distinct calendar DAYS with at least one IV observation.

    The rank gate counts days, not rows: the poller writes many observations a
    day, so 52 rows can all live inside one afternoon — a rank over that window
    is undefined no matter how many rows exist.
    """
    with session_scope() as session:
        count = session.execute(
            select(func.count(func.distinct(func.date(IVSnapshotRow.ts)))).where(
                IVSnapshotRow.symbol == symbol.upper()
            )
        ).scalar_one()
    return int(count or 0)


def history_span(symbol: str):
    """First and last observation timestamps, for honest window labels."""
    with session_scope() as session:
        row = session.execute(
            select(func.min(IVSnapshotRow.ts), func.max(IVSnapshotRow.ts)).where(
                IVSnapshotRow.symbol == symbol.upper()
            )
        ).one()
    first, last = row
    if first is None or last is None:
        return None, None
    return _aware(first), _aware(last)


def observation_count(symbol: str) -> int:
    with session_scope() as session:
        return int(
            session.execute(
                select(func.count(IVSnapshotRow.id)).where(IVSnapshotRow.symbol == symbol.upper())
            ).scalar_one()
        )


def daily_closing_iv(symbol: str, days: int = 365) -> list[tuple[str, float]]:
    """One observation per day — the last of each day. Feeds the UI's IV chart."""
    by_day: dict[str, float] = {}
    for point in iv_history(symbol, days=days):
        by_day[point.ts.date().isoformat()] = point.atm_iv
    return sorted(by_day.items())


def _aware(moment: datetime) -> datetime:
    """SQLite round-trips datetimes without tzinfo; put UTC back on."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


class IVPoller:
    """Writes one ATM IV observation per symbol per tick.

    Runs on the same APScheduler instance as the main loop but on its own
    interval, and — unlike the trading loop — keeps sampling right up to the
    close so the history is dense enough to be worth charting.
    """

    def __init__(self, chain_client, symbols: list[str], dte_target: int = 30) -> None:
        self._chains = chain_client
        self.symbols = [s.upper() for s in symbols]
        self.dte_target = dte_target

    def poll_once(self) -> dict[str, float]:
        """Sample every symbol. Returns what was stored; never raises on one bad name."""
        from skew.vol.implied import atm_implied_vol
        from skew.vol.term import term_structure_slope

        stored: dict[str, float] = {}
        for symbol in self.symbols:
            try:
                chain = self._chains.get_chain(symbol, dte_min=7, dte_max=90)
                atm = atm_implied_vol(chain, target_dte=self.dte_target)
                if atm is None:
                    log.warning("No ATM IV available for %s this tick", symbol)
                    continue
                slope = term_structure_slope(chain)
                if record_iv(
                    symbol,
                    atm_iv=atm.iv,
                    spot=chain.spot,
                    dte=atm.dte,
                    term_slope=slope.slope if slope else 0.0,
                ):
                    stored[symbol] = atm.iv
            except Exception as exc:  # noqa: BLE001 — one bad symbol must not stop the poll
                log.warning("IV poll failed for %s: %s", symbol, exc)
        return stored
