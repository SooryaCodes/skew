"""Premium-buying structures — what we build when volatility is cheap.

When implied volatility sits at or below what the underlying is actually
realizing, movement is underpriced and the edge is in owning it rather than
selling it.

A debit spread buys the nearer option and sells a further one to reduce the
cost. **The debit paid is the maximum loss**, known before submission, which is
what keeps these inside the defined-risk rule.

Note the asymmetry with the credit side: a debit spread is a long-vega,
negative-theta position. Time is working against it, so these are built closer
to the money and with a shorter horizon than the premium sales.
"""

from __future__ import annotations

import logging
from datetime import date

from skew.data.chains import OptionChain
from skew.models import Structure
from skew.structures.base import StructureError, assemble, leg_from_contract
from skew.structures.selection import (
    DEFAULT_WIDTH_PCT,
    BudgetTooTight,
    choose_expiry,
    select_debit_vertical,
)

log = logging.getLogger(__name__)


def _build(
    chain: OptionChain,
    kind: str,
    right: str,
    expiry: date | None,
    long_delta: float,
    width_pct: float,
    qty: int,
    dte_min: int,
    dte_max: int,
    min_open_interest: int,
    max_spread_pct: float,
    as_of: date | None,
    budget: float | None = None,
) -> Structure | None:
    ref = as_of or chain.as_of.date()
    chosen = expiry or choose_expiry(chain, dte_min, dte_max, as_of=ref)
    if chosen is None:
        return None

    picked = select_debit_vertical(
        chain,
        chosen,
        right,
        long_delta,
        width_pct,
        min_open_interest,
        max_spread_pct,
        budget=budget,
    )
    if picked is None:
        return None

    long_leg, short = picked
    try:
        return assemble(
            chain.symbol,
            kind,
            [
                leg_from_contract(long_leg, "BUY", 1),
                leg_from_contract(short, "SELL", 1),
            ],
            spot=chain.spot,
            qty=qty,
            as_of=ref,
            max_loss_cap=budget,
        )
    except StructureError as exc:
        log.debug("%s on %s rejected at assembly: %s", kind, chain.symbol, exc)
        return None


def call_debit_spread(
    chain: OptionChain,
    expiry: date | None = None,
    long_delta: float = 0.50,
    width_pct: float = DEFAULT_WIDTH_PCT,
    qty: int = 1,
    dte_min: int = 21,
    dte_max: int = 45,
    min_open_interest: int = 0,
    max_spread_pct: float = 1.0,
    as_of: date | None = None,
    budget: float | None = None,
) -> Structure | None:
    """Buy a call, sell a higher one. Long vega, defined risk."""
    return _build(
        chain,
        "CALL_DEBIT",
        "CALL",
        expiry,
        long_delta,
        width_pct,
        qty,
        dte_min,
        dte_max,
        min_open_interest,
        max_spread_pct,
        as_of,
        budget=budget,
    )


def put_debit_spread(
    chain: OptionChain,
    expiry: date | None = None,
    long_delta: float = 0.50,
    width_pct: float = DEFAULT_WIDTH_PCT,
    qty: int = 1,
    dte_min: int = 21,
    dte_max: int = 45,
    min_open_interest: int = 0,
    max_spread_pct: float = 1.0,
    as_of: date | None = None,
    budget: float | None = None,
) -> Structure | None:
    """Buy a put, sell a lower one."""
    return _build(
        chain,
        "PUT_DEBIT",
        "PUT",
        expiry,
        long_delta,
        width_pct,
        qty,
        dte_min,
        dte_max,
        min_open_interest,
        max_spread_pct,
        as_of,
        budget=budget,
    )


def build_debit_candidates(
    chain: OptionChain,
    qty: int = 1,
    dte_min: int = 21,
    dte_max: int = 45,
    long_delta: float = 0.50,
    width_pct: float = DEFAULT_WIDTH_PCT,
    min_open_interest: int = 0,
    max_spread_pct: float = 1.0,
    as_of: date | None = None,
    budget: float | None = None,
) -> list[Structure]:
    """Both debit verticals, when the chain supports them.

    We build one on each side deliberately. The desk has no directional view —
    offering only a call debit spread would smuggle one in, and the point is to
    own volatility, not to pick a way for the underlying to go.

    Budget-sized like the credit side: the widest spread whose debit fits the
    per-trade cap. BudgetTooTight propagates only when nothing could be built.
    """
    kwargs = {
        "qty": qty,
        "dte_min": dte_min,
        "dte_max": dte_max,
        "long_delta": long_delta,
        "width_pct": width_pct,
        "min_open_interest": min_open_interest,
        "max_spread_pct": max_spread_pct,
        "as_of": as_of,
        "budget": budget,
    }
    built: list[Structure] = []
    tight: BudgetTooTight | None = None
    for build in (
        lambda: call_debit_spread(chain, **kwargs),
        lambda: put_debit_spread(chain, **kwargs),
    ):
        try:
            structure = build()
        except BudgetTooTight as exc:
            tight = tight or exc
            continue
        if structure is not None:
            built.append(structure)
    if not built and tight is not None:
        raise tight
    return built
