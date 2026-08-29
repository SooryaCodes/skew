"""Premium-selling structures — what we build when volatility is rich.

A credit spread sells an option and buys a further out-of-the-money one as
protection. The bought leg is what caps the loss, and it is why nothing in this
package can ever produce a naked short option.

    SELL  SPY 580 put   collect $2.00
    BUY   SPY 575 put   pay     $1.20
                        ───────────────
    net credit          $0.80  ->  $80 collected

    max profit  $80, if SPY stays above 580
    max loss    (580 − 575) × 100 − 80 = $420

Note what that position needs in order to win: SPY up, sideways, or slightly
down. It is direction-tolerant by construction, which is exactly why this desk
uses it to express a view about volatility rather than about price.
"""

from __future__ import annotations

import logging
from datetime import date

from skew.data.chains import OptionChain
from skew.models import Structure
from skew.structures.base import StructureError, assemble, leg_from_contract
from skew.structures.selection import (
    DEFAULT_WIDTH_PCT,
    choose_expiry,
    select_condor_wings,
    select_credit_vertical,
)

log = logging.getLogger(__name__)


def put_credit_spread(
    chain: OptionChain,
    expiry: date | None = None,
    short_delta: float = 0.25,
    width_pct: float = DEFAULT_WIDTH_PCT,
    qty: int = 1,
    dte_min: int = 21,
    dte_max: int = 45,
    min_open_interest: int = 0,
    max_spread_pct: float = 1.0,
    as_of: date | None = None,
) -> Structure | None:
    """Sell a put, buy a lower one. The bread and butter when vol is rich."""
    ref = as_of or chain.as_of.date()
    chosen = expiry or choose_expiry(chain, dte_min, dte_max, as_of=ref)
    if chosen is None:
        return None

    picked = select_credit_vertical(
        chain, chosen, "PUT", short_delta, width_pct, min_open_interest, max_spread_pct
    )
    if picked is None:
        return None

    short, long_leg = picked
    try:
        return assemble(
            chain.symbol,
            "PUT_CREDIT",
            [
                leg_from_contract(short, "SELL", 1),
                leg_from_contract(long_leg, "BUY", 1),
            ],
            spot=chain.spot,
            qty=qty,
            as_of=ref,
        )
    except StructureError as exc:
        log.debug("put credit spread on %s rejected at assembly: %s", chain.symbol, exc)
        return None


def call_credit_spread(
    chain: OptionChain,
    expiry: date | None = None,
    short_delta: float = 0.25,
    width_pct: float = DEFAULT_WIDTH_PCT,
    qty: int = 1,
    dte_min: int = 21,
    dte_max: int = 45,
    min_open_interest: int = 0,
    max_spread_pct: float = 1.0,
    as_of: date | None = None,
) -> Structure | None:
    """Sell a call, buy a higher one. Mirror image of the put credit spread."""
    ref = as_of or chain.as_of.date()
    chosen = expiry or choose_expiry(chain, dte_min, dte_max, as_of=ref)
    if chosen is None:
        return None

    picked = select_credit_vertical(
        chain, chosen, "CALL", short_delta, width_pct, min_open_interest, max_spread_pct
    )
    if picked is None:
        return None

    short, long_leg = picked
    try:
        return assemble(
            chain.symbol,
            "CALL_CREDIT",
            [
                leg_from_contract(short, "SELL", 1),
                leg_from_contract(long_leg, "BUY", 1),
            ],
            spot=chain.spot,
            qty=qty,
            as_of=ref,
        )
    except StructureError as exc:
        log.debug("call credit spread on %s rejected at assembly: %s", chain.symbol, exc)
        return None


def iron_condor(
    chain: OptionChain,
    expiry: date | None = None,
    short_delta: float = 0.20,
    width_pct: float = DEFAULT_WIDTH_PCT,
    qty: int = 1,
    dte_min: int = 21,
    dte_max: int = 45,
    min_open_interest: int = 0,
    max_spread_pct: float = 1.0,
    as_of: date | None = None,
) -> Structure | None:
    """A put credit spread and a call credit spread on the same expiry.

    Exactly four legs — the most Alpaca permits for an options mleg order.
    Collects premium from both sides and profits if the underlying stays in a
    range. Only one wing can finish in the money, so the max loss is the wider
    wing minus the credit, not the sum of both wings.
    """
    ref = as_of or chain.as_of.date()
    chosen = expiry or choose_expiry(chain, dte_min, dte_max, as_of=ref)
    if chosen is None:
        return None

    wings = select_condor_wings(
        chain, chosen, short_delta, width_pct, min_open_interest, max_spread_pct
    )
    if wings is None:
        return None

    short_put, long_put, short_call, long_call = wings
    try:
        return assemble(
            chain.symbol,
            "IRON_CONDOR",
            [
                leg_from_contract(short_put, "SELL", 1),
                leg_from_contract(long_put, "BUY", 1),
                leg_from_contract(short_call, "SELL", 1),
                leg_from_contract(long_call, "BUY", 1),
            ],
            spot=chain.spot,
            qty=qty,
            as_of=ref,
        )
    except StructureError as exc:
        log.debug("iron condor on %s rejected at assembly: %s", chain.symbol, exc)
        return None


def build_credit_candidates(
    chain: OptionChain,
    qty: int = 1,
    dte_min: int = 21,
    dte_max: int = 45,
    short_delta: float = 0.25,
    width_pct: float = DEFAULT_WIDTH_PCT,
    min_open_interest: int = 0,
    max_spread_pct: float = 1.0,
    as_of: date | None = None,
) -> list[Structure]:
    """Two or three fully-specified premium-selling candidates.

    Deliberately a short list. The model downstream picks among pre-validated
    options; handing it thirty near-identical spreads would be handing it a
    search problem instead of a choice.
    """
    kwargs = {
        "qty": qty,
        "dte_min": dte_min,
        "dte_max": dte_max,
        "width_pct": width_pct,
        "min_open_interest": min_open_interest,
        "max_spread_pct": max_spread_pct,
        "as_of": as_of,
    }
    built = [
        put_credit_spread(chain, short_delta=short_delta, **kwargs),
        iron_condor(chain, short_delta=max(0.15, short_delta - 0.05), **kwargs),
        call_credit_spread(chain, short_delta=short_delta, **kwargs),
    ]
    return [s for s in built if s is not None]
