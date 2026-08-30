"""Implied volatility extraction from the chain.

**We never invert Black-Scholes here.** Alpaca returns ``implied_volatility``
per contract on the snapshot endpoint; re-deriving it would be reimplementing a
solved problem and introducing error. See docs/01-ARCHITECTURE.md §3.

Two things come out of this module: the single ATM number that feeds the
variance risk premium, and the IV-vs-strike slice that the frontend renders as
the skew curve — the shape the product is named after.

All IVs are annualised decimals (0.241 = 24.1%), per ``skew.vol.realized``.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from pydantic import BaseModel

from skew.models import Right, SkewPoint

if TYPE_CHECKING:  # pragma: no cover
    from skew.data.chains import ContractQuote, OptionChain


class ATMQuote(BaseModel):
    """The at-the-money implied volatility for one expiry."""

    symbol: str
    expiry: date
    dte: int
    iv: float
    spot: float
    call_iv: float | None = None
    put_iv: float | None = None
    interpolated: bool = False


def _interpolate_iv_at_spot(
    contracts: list[ContractQuote], spot: float
) -> tuple[float | None, bool]:
    """Linear-interpolate IV between the two strikes bracketing spot.

    Taking the nearest strike alone is biased whenever spot sits between
    strikes, which for a $580 underlying on $5 strike spacing is most of the
    time. Returns ``(iv, interpolated)``; falls back to the nearest strike when
    spot is outside the listed range.
    """
    usable = sorted((c for c in contracts if c.is_tradeable and c.iv > 0), key=lambda c: c.strike)
    if not usable:
        return None, False
    if len(usable) == 1:
        return usable[0].iv, False

    below = [c for c in usable if c.strike <= spot]
    above = [c for c in usable if c.strike >= spot]
    if not below or not above:
        nearest = min(usable, key=lambda c: abs(c.strike - spot))
        return nearest.iv, False

    lo, hi = below[-1], above[0]
    if lo.strike == hi.strike:
        return lo.iv, False

    weight = (spot - lo.strike) / (hi.strike - lo.strike)
    return lo.iv + weight * (hi.iv - lo.iv), True


def atm_implied_vol(
    chain: OptionChain,
    target_dte: int = 30,
    expiry: date | None = None,
    as_of: date | None = None,
) -> ATMQuote | None:
    """ATM implied volatility for the expiry nearest ``target_dte``.

    Averages the call and the put. At the money the two should price to the same
    IV under put-call parity; averaging cancels the small dislocations that
    order flow leaves on one side, and is what every vol desk does.

    Returns None — never a zero, never a guess — when the chain cannot support
    the calculation. Callers abstain on None.
    """
    ref = as_of or chain.as_of.date()
    chosen = expiry or chain.nearest_expiry(target_dte, as_of=ref)
    if chosen is None:
        return None

    contracts = chain.by_expiry(chosen)
    if not contracts:
        return None

    call_iv, call_interp = _interpolate_iv_at_spot(
        [c for c in contracts if c.right == "CALL"], chain.spot
    )
    put_iv, put_interp = _interpolate_iv_at_spot(
        [c for c in contracts if c.right == "PUT"], chain.spot
    )

    both = [v for v in (call_iv, put_iv) if v is not None and v > 0]
    if not both:
        return None

    return ATMQuote(
        symbol=chain.symbol,
        expiry=chosen,
        dte=(chosen - ref).days,
        iv=sum(both) / len(both),
        spot=chain.spot,
        call_iv=call_iv,
        put_iv=put_iv,
        interpolated=call_interp or put_interp,
    )


def skew_slice(
    chain: OptionChain,
    expiry: date | None = None,
    target_dte: int = 30,
    width_pct: float = 0.15,
    as_of: date | None = None,
    min_open_interest: int = 10,
    max_spread_pct: float = 0.30,
) -> list[SkewPoint]:
    """IV plotted across strike — the curve in the header.

    Uses **out-of-the-money contracts only**: puts below spot, calls above. That
    is the standard construction, and it matters. In-the-money options are
    thinly quoted and their IVs are noisy, so including them would put a kink in
    the curve that is an artefact of the data rather than a property of the
    market.

    The shape this produces is the skew itself: lower strikes carry higher IV
    because people pay up for downside protection. That asymmetry is the whole
    reason the product has this name.
    """
    ref = as_of or chain.as_of.date()
    chosen = expiry or chain.nearest_expiry(target_dte, as_of=ref)
    if chosen is None or chain.spot <= 0:
        return []

    lo, hi = chain.spot * (1 - width_pct), chain.spot * (1 + width_pct)

    # Hygiene before plotting. A jagged skew is not a market feature — it is
    # stale one-sided quotes on illiquid strikes leaking into the picture. Only
    # two-sided, open-interest-backed quotes with a sane spread make the curve;
    # is_tradeable already requires a non-zero bid and an IV.
    def clean(c) -> bool:
        return (
            c.is_tradeable
            and c.open_interest >= min_open_interest
            and c.spread_pct <= max_spread_pct
        )

    candidates = [c for c in chain.by_expiry(chosen) if clean(c) and lo <= c.strike <= hi]

    # Drop strikes beyond ~3 sigma of the expiry's own implied move: quotes out
    # there are placeholder marks, and they oscillate.
    atm = min(candidates, key=lambda c: abs(c.strike - chain.spot), default=None)
    if atm is not None and atm.iv > 0:
        dte = max((chosen - ref).days, 1)
        band = 3.0 * chain.spot * atm.iv * (dte / 365.0) ** 0.5
        candidates = [c for c in candidates if abs(c.strike - chain.spot) <= band]

    points: list[SkewPoint] = []
    for c in candidates:
        otm = (c.right == "PUT" and c.strike <= chain.spot) or (
            c.right == "CALL" and c.strike > chain.spot
        )
        if not otm:
            continue
        points.append(
            SkewPoint(
                strike=c.strike,
                iv=c.iv,
                right=c.right,
                delta=c.delta or None,
                moneyness=c.strike / chain.spot,
            )
        )

    points.sort(key=lambda p: p.strike)
    return points


def skew_steepness(points: list[SkewPoint], spot: float) -> float:
    """IV difference between the 10%-OTM put and the 10%-OTM call, in decimals.

    Positive is the normal equity shape — downside protection is bid. A flat or
    inverted curve means the market has stopped paying for crash protection,
    which is context worth showing but is not itself a trading signal.
    """
    if not points or spot <= 0:
        return 0.0
    puts = [p for p in points if p.right == "PUT"]
    calls = [p for p in points if p.right == "CALL"]
    if not puts or not calls:
        return 0.0
    put_wing = min(puts, key=lambda p: abs(p.moneyness - 0.90))
    call_wing = min(calls, key=lambda p: abs(p.moneyness - 1.10))
    return float(put_wing.iv - call_wing.iv)


def iv_at_delta(
    chain: OptionChain, expiry: date, right: Right, target_delta: float
) -> ContractQuote | None:
    """The tradeable contract whose delta is closest to ``target_delta``.

    Delta is compared on absolute value so callers can pass 0.25 and get the
    right answer for a put (whose delta is negative) without special-casing.
    """
    pool = [
        c
        for c in chain.by_expiry(expiry)
        if c.right == right and c.is_tradeable and c.delta not in (0.0, None)
    ]
    if not pool:
        return None
    return min(pool, key=lambda c: abs(abs(c.delta) - abs(target_delta)))
