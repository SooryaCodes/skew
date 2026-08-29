"""Option chain fetch and parsing.

docs/01-ARCHITECTURE.md §3: **Alpaca gives you IV and Greeks. Do not compute
them.** The chain snapshot carries ``implied_volatility`` and a full ``greeks``
block per contract, so there is no Black-Scholes inversion anywhere in this
module. (We do implement Black-Scholes in ``skew/stress/`` — but there we are
pricing a hypothetical, not reading a quote.)

One thing the spec did not anticipate: **open interest is not on the snapshot.**
``OptionsSnapshot`` carries only symbol / latest_trade / latest_quote /
implied_volatility / greeks. Open interest lives on ``OptionContract`` in the
*trading* API, so the liquidity gate needs a second fetch joined by contract
symbol. It changes far more slowly than a quote, so it is cached for much longer.

Per-contract daily volume is not available either without a bars call per
contract, which is far too expensive for a five-minute loop. The liquidity gate
therefore keys on open interest, quote presence and bid-ask width, and
``MIN_VOLUME`` defaults to 0. Documented rather than faked.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from skew.models import Right

log = logging.getLogger(__name__)

# Open interest is published once a day; there is no point re-fetching it every loop.
OI_CACHE_TTL_SECONDS = 3600
CHAIN_CACHE_TTL_SECONDS = 60


class ContractQuote(BaseModel):
    """One option contract, everything we know about it right now."""

    symbol: str
    underlying: str
    strike: float
    expiry: date
    right: Right

    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    iv: float = 0.0

    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0

    open_interest: int = 0
    volume: int = 0

    @property
    def mid(self) -> float:
        """Mid price, or the last trade when only one side is quoted.

        Returns 0.0 when there is nothing usable — callers must treat that as
        "no quote" and skip the contract rather than pricing off a zero.
        """
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.last if self.last > 0 else 0.0

    @property
    def spread_pct(self) -> float:
        m = self.mid
        if m <= 0 or self.ask <= 0:
            return 1.0
        return (self.ask - self.bid) / m

    @property
    def has_quote(self) -> bool:
        return self.bid > 0 and self.ask > 0 and self.ask >= self.bid

    @property
    def is_tradeable(self) -> bool:
        """Skip any contract with no quote, a zero bid, or no implied vol."""
        return self.has_quote and self.iv > 0

    def dte(self, as_of: date | None = None) -> int:
        return (self.expiry - (as_of or datetime.now(UTC).date())).days


class OptionChain(BaseModel):
    """A parsed chain for one underlying at one moment."""

    symbol: str
    spot: float
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
    contracts: list[ContractQuote] = Field(default_factory=list)

    # ---------------- selection helpers ----------------

    @property
    def expiries(self) -> list[date]:
        return sorted({c.expiry for c in self.contracts})

    def by_expiry(self, expiry: date) -> list[ContractQuote]:
        return [c for c in self.contracts if c.expiry == expiry]

    def tradeable(self) -> list[ContractQuote]:
        return [c for c in self.contracts if c.is_tradeable]

    def expiries_within(self, dte_min: int, dte_max: int, as_of: date | None = None) -> list[date]:
        ref = as_of or self.as_of.date()
        return [e for e in self.expiries if dte_min <= (e - ref).days <= dte_max]

    def nearest_expiry(self, target_dte: int, as_of: date | None = None) -> date | None:
        ref = as_of or self.as_of.date()
        future = [e for e in self.expiries if (e - ref).days > 0]
        if not future:
            return None
        return min(future, key=lambda e: abs((e - ref).days - target_dte))

    def atm_contract(self, expiry: date, right: Right = "CALL") -> ContractQuote | None:
        """The tradeable contract whose strike sits closest to spot."""
        pool = [c for c in self.by_expiry(expiry) if c.right == right and c.is_tradeable]
        if not pool:
            return None
        return min(pool, key=lambda c: abs(c.strike - self.spot))


# ----------------------------------------------------------------------
# OCC symbol parsing — pure, no network, fully testable
# ----------------------------------------------------------------------


def parse_occ_symbol(symbol: str) -> tuple[str, date, Right, float]:
    """Decompose an OCC contract symbol.

        SPY   250919 P 00580000
        │     │      │ │
        │     │      │ └── strike x 1000 -> $580.00
        │     │      └──── P = put, C = call
        │     └─────────── expires 2025-09-19
        └───────────────── underlying

    Parsed from the right, because the root is variable length and Alpaca omits
    the space padding the OCC spec allows.
    """
    s = symbol.strip().upper().replace(" ", "")
    if len(s) < 16:
        raise ValueError(f"Not an OCC option symbol: {symbol!r}")

    strike_raw, right_raw, yy, mm, dd = s[-8:], s[-9], s[-15:-13], s[-13:-11], s[-11:-9]
    root = s[:-15]

    if not (strike_raw.isdigit() and yy.isdigit() and mm.isdigit() and dd.isdigit()):
        raise ValueError(f"Not an OCC option symbol: {symbol!r}")
    if right_raw not in ("C", "P"):
        raise ValueError(f"Option right must be C or P, got {right_raw!r} in {symbol!r}")
    if not root:
        raise ValueError(f"Missing underlying root in {symbol!r}")

    right: Right = "CALL" if right_raw == "C" else "PUT"
    return root, date(2000 + int(yy), int(mm), int(dd)), right, int(strike_raw) / 1000.0


def build_occ_symbol(underlying: str, expiry: date, right: Right, strike: float) -> str:
    """Inverse of :func:`parse_occ_symbol`. Used to build fixtures and tests."""
    r = "C" if right == "CALL" else "P"
    return f"{underlying.upper()}{expiry:%y%m%d}{r}{round(strike * 1000):08d}"


# ----------------------------------------------------------------------
# Snapshot -> ContractQuote
# ----------------------------------------------------------------------


def _num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return default if out != out else out  # NaN guard


def contract_from_snapshot(
    symbol: str,
    snapshot: Any,
    open_interest: int = 0,
    volume: int = 0,
) -> ContractQuote | None:
    """Convert one Alpaca ``OptionsSnapshot`` into a :class:`ContractQuote`.

    Returns None for a symbol that does not parse as an option contract, rather
    than raising — one malformed key must not take down a whole chain fetch.
    """
    try:
        underlying, expiry, right, strike = parse_occ_symbol(symbol)
    except ValueError:
        log.warning("skipping unparseable contract symbol %s", symbol)
        return None

    quote = getattr(snapshot, "latest_quote", None)
    trade = getattr(snapshot, "latest_trade", None)
    greeks = getattr(snapshot, "greeks", None)

    return ContractQuote(
        symbol=symbol.upper(),
        underlying=underlying,
        strike=strike,
        expiry=expiry,
        right=right,
        bid=_num(getattr(quote, "bid_price", 0.0)),
        ask=_num(getattr(quote, "ask_price", 0.0)),
        last=_num(getattr(trade, "price", 0.0)),
        iv=_num(getattr(snapshot, "implied_volatility", 0.0)),
        delta=_num(getattr(greeks, "delta", 0.0)),
        gamma=_num(getattr(greeks, "gamma", 0.0)),
        theta=_num(getattr(greeks, "theta", 0.0)),
        vega=_num(getattr(greeks, "vega", 0.0)),
        rho=_num(getattr(greeks, "rho", 0.0)),
        open_interest=int(open_interest or 0),
        volume=int(volume or 0),
    )


def build_chain(
    symbol: str,
    spot: float,
    snapshots: dict[str, Any],
    open_interest: dict[str, int] | None = None,
    as_of: datetime | None = None,
) -> OptionChain:
    """Assemble an :class:`OptionChain` from raw snapshots. Pure; no network."""
    oi = open_interest or {}
    contracts: list[ContractQuote] = []
    for contract_symbol, snap in snapshots.items():
        parsed = contract_from_snapshot(
            contract_symbol, snap, open_interest=oi.get(contract_symbol.upper(), 0)
        )
        if parsed is not None:
            contracts.append(parsed)

    contracts.sort(key=lambda c: (c.expiry, c.right, c.strike))
    return OptionChain(
        symbol=symbol.upper(),
        spot=spot,
        as_of=as_of or datetime.now(UTC),
        contracts=contracts,
    )


# ----------------------------------------------------------------------
# The networked client
# ----------------------------------------------------------------------


class ChainClient:
    """Fetches chains, spots and open interest, with per-symbol caching.

    Greeks are only on the snapshot endpoints and are computationally expensive:
    one chain fetch per symbol per loop, never one per candidate.
    """

    def __init__(self, broker: Any) -> None:
        # ``broker`` is a skew.data.broker.Broker. Injected rather than
        # constructed so tests can pass a fake with no network.
        self._broker = broker
        self._chain_cache: dict[str, tuple[float, OptionChain]] = {}
        self._oi_cache: dict[str, tuple[float, dict[str, int]]] = {}

    def invalidate(self, symbol: str | None = None) -> None:
        """Drop cached chains. Called at the top of each loop cycle."""
        if symbol is None:
            self._chain_cache.clear()
        else:
            self._chain_cache.pop(symbol.upper(), None)

    def open_interest_map(self, symbol: str, expiries: list[date] | None = None) -> dict[str, int]:
        """Contract symbol -> open interest, from the trading API.

        Cached for an hour: open interest is published daily, so re-fetching it
        every five minutes would burn rate limit for no new information.
        """
        key = symbol.upper()
        hit = self._oi_cache.get(key)
        if hit and (time.monotonic() - hit[0]) < OI_CACHE_TTL_SECONDS:
            return hit[1]

        oi = self._broker.fetch_open_interest(key, expiries=expiries)
        self._oi_cache[key] = (time.monotonic(), oi)
        return oi

    def get_chain(
        self,
        symbol: str,
        dte_min: int,
        dte_max: int,
        strike_window_pct: float = 0.20,
        use_cache: bool = True,
    ) -> OptionChain:
        """Fetch one underlying's chain, bounded by expiry and strike window.

        The strike window keeps the payload small: a full SPY chain is thousands
        of contracts and we only ever trade within roughly 20% of spot.
        """
        key = symbol.upper()
        if use_cache:
            hit = self._chain_cache.get(key)
            if hit and (time.monotonic() - hit[0]) < CHAIN_CACHE_TTL_SECONDS:
                return hit[1]

        spot = self._broker.fetch_spot(key)
        if spot <= 0:
            raise ValueError(
                f"No usable spot price for {key}. Abstaining rather than pricing off zero."
            )

        today = datetime.now(UTC).date()
        snapshots = self._broker.fetch_option_chain(
            key,
            expiry_gte=today,
            expiry_lte=today + timedelta(days=dte_max),
            strike_gte=spot * (1 - strike_window_pct),
            strike_lte=spot * (1 + strike_window_pct),
        )
        if not snapshots:
            raise ValueError(f"Empty option chain for {key}. Abstaining.")

        chain = build_chain(key, spot, snapshots)
        expiries = chain.expiries_within(max(0, dte_min - 10), dte_max + 10, as_of=today)
        oi = self.open_interest_map(key, expiries=expiries or None)
        if oi:
            for contract in chain.contracts:
                contract.open_interest = oi.get(contract.symbol, contract.open_interest)

        self._chain_cache[key] = (time.monotonic(), chain)
        return chain
