"""Strike selection by delta target.

**By delta, not by dollar distance.** Delta is roughly the probability of
finishing in the money, so a 0.25-delta short strike means about the same thing
on a $770 index and a $200 single name. Selecting "$20 out of the money" means
completely different risk on those two, and it is the kind of shortcut that
looks fine in a demo and is wrong in the account.

Delta comes from the Alpaca chain — we never derive it.

Every function here filters for tradeability first: no quote, no bid, no
implied volatility, or no open interest means the contract does not exist as far
as this desk is concerned. A structure priced off a contract with no bid is a
structure that cannot be closed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING

from skew.models import Right

if TYPE_CHECKING:  # pragma: no cover
    from skew.data.chains import ContractQuote, OptionChain

log = logging.getLogger(__name__)

# Target strike width as a fraction of spot. 0.75% puts a SPY spread around $5
# wide and an NVDA spread around $1.50 — economically the same structure on
# very different underlyings.
DEFAULT_WIDTH_PCT = 0.0075
MIN_WIDTH_DOLLARS = 1.0

# A slightly worse fill than the quoted mid must not push the realized max loss
# past the cap, so the width search prices every candidate with this margin.
BUDGET_FILL_MARGIN = 1.10


class BudgetTooTight(Exception):
    """Even the narrowest listed strike interval exceeds the per-trade budget.

    Deliberately NOT a StructureError: assembly-level catches must not swallow
    it. It carries the numbers so the desk can abstain with a reason a human can
    check — "narrowest available spread is 5 points, max loss $487, exceeds
    remaining headroom $159" — instead of building a candidate it already knows
    will be refused.
    """

    def __init__(self, symbol: str, narrowest_width: float, est_max_loss: float, budget: float):
        self.symbol = symbol
        self.narrowest_width = narrowest_width
        self.est_max_loss = est_max_loss
        self.budget = budget
        super().__init__(
            f"Narrowest available spread on {symbol} is {narrowest_width:g} points — "
            f"estimated max loss ${est_max_loss:,.0f} exceeds the remaining per-trade "
            f"headroom ${budget:,.0f}. Abstaining rather than building an oversized "
            "structure."
        )


def usable_contracts(
    chain: OptionChain,
    expiry: date,
    right: Right,
    min_open_interest: int = 0,
    max_spread_pct: float = 1.0,
) -> list[ContractQuote]:
    """Tradeable contracts for one expiry and right, sorted by strike.

    The liquidity gate re-checks these thresholds on the assembled structure and
    writes the human-facing reason. Filtering here as well is not duplication —
    it stops us building a candidate around a contract we already know is junk,
    so the gate output stays about genuine near-misses.
    """
    out = [
        c
        for c in chain.by_expiry(expiry)
        if c.right == right
        and c.is_tradeable
        and c.open_interest >= min_open_interest
        and c.spread_pct <= max_spread_pct
    ]
    out.sort(key=lambda c: c.strike)
    return out


def by_delta(contracts: list[ContractQuote], target_delta: float) -> ContractQuote | None:
    """The contract whose |delta| is nearest the target.

    Absolute value throughout, so callers pass 0.25 and get the right answer for
    a put — whose delta is negative — without special-casing at every site.
    """
    pool = [c for c in contracts if c.delta not in (0.0, None)]
    if not pool:
        return None
    return min(pool, key=lambda c: abs(abs(c.delta) - abs(target_delta)))


def strikes_away(
    contracts: list[ContractQuote],
    anchor: ContractQuote,
    n: int,
    direction: int,
) -> ContractQuote | None:
    """Step ``n`` listed strikes from ``anchor``.

    ``direction`` is +1 for higher strikes, −1 for lower. Steps through the
    strikes that actually exist and are tradeable, rather than assuming uniform
    spacing — real chains have $1 strikes near the money and $5 further out, so
    arithmetic on strike price is wrong.
    """
    if n <= 0:
        return None
    ordered = sorted(contracts, key=lambda c: c.strike)
    try:
        index = next(i for i, c in enumerate(ordered) if c.symbol == anchor.symbol)
    except StopIteration:
        return None

    target = index + (n * direction)
    if not 0 <= target < len(ordered):
        return None
    return ordered[target]


def target_width(spot: float, width_pct: float = DEFAULT_WIDTH_PCT) -> float:
    """The strike width we want, in dollars, scaled to the underlying.

    A fixed "two strikes out" is the wrong rule. SPY lists $1 strikes near the
    money, so two strikes is a $2-wide spread on a $769 underlying — the credit
    barely covers the spread crossed to get in, and the risk/reward is dominated
    by frictions. Scaling to a fraction of spot keeps the structure economically
    the same shape on a $770 index and a $200 single name.
    """
    return max(MIN_WIDTH_DOLLARS, spot * width_pct)


def _walk_to_width(
    contracts: list[ContractQuote],
    anchor: ContractQuote,
    direction: int,
    want_width: float,
    max_steps: int = 25,
) -> ContractQuote | None:
    """Step outward from ``anchor`` until the strike width reaches ``want_width``.

    Walks listed strikes rather than doing arithmetic on price, because real
    chains mix $1 and $5 spacing. Falls back to the widest usable contract found
    when nothing reaches the target, so a thin chain still produces a defined-risk
    structure rather than nothing at all.
    """
    best: ContractQuote | None = None
    for n in range(1, max_steps + 1):
        candidate = strikes_away(contracts, anchor, n, direction)
        if candidate is None:
            break
        if candidate.symbol == anchor.symbol:
            continue
        # The far leg must be cheaper than the anchor — true for both the
        # protective leg of a credit spread and the sold leg of a debit spread.
        # If it is not, the quotes are stale and the max-loss arithmetic would
        # be wrong.
        if candidate.mid >= anchor.mid:
            continue

        best = candidate
        if abs(candidate.strike - anchor.strike) >= want_width:
            return candidate
    return best


def _walk_to_budget(
    contracts: list[ContractQuote],
    anchor: ContractQuote,
    direction: int,
    budget: float,
    est_loss: Callable[[ContractQuote, ContractQuote], float],
    max_steps: int = 25,
) -> ContractQuote | None:
    """The WIDEST strike whose estimated max loss (with fill margin) fits ``budget``.

    Works backwards from the risk budget instead of forwards from a width
    target: walks outward from ``anchor`` through the strikes that actually
    exist, keeps the widest one that still fits, and raises
    :class:`BudgetTooTight` when even the first interval does not — the caller
    abstains rather than building a candidate its own gate must refuse.
    """
    narrowest: tuple[float, float] | None = None  # (width, est) of the first interval
    best: ContractQuote | None = None
    for n in range(1, max_steps + 1):
        candidate = strikes_away(contracts, anchor, n, direction)
        if candidate is None:
            break
        if candidate.symbol == anchor.symbol:
            continue
        # Stale-quote guard, same as the width walk: the far leg must be cheaper.
        if candidate.mid >= anchor.mid:
            continue

        estimated = est_loss(anchor, candidate) * BUDGET_FILL_MARGIN
        width = abs(candidate.strike - anchor.strike)
        if narrowest is None:
            narrowest = (width, estimated)
        if estimated <= budget:
            best = candidate  # keep walking — a wider fit may still exist
        else:
            break  # loss grows with width; the first miss ends the walk

    if best is not None:
        return best
    if narrowest is not None:
        raise BudgetTooTight(anchor.underlying, narrowest[0], narrowest[1], budget)
    return None


def credit_vertical_loss(short: ContractQuote, long_leg: ContractQuote) -> float:
    """Estimated max loss in dollars for one credit vertical: width − credit."""
    width = abs(short.strike - long_leg.strike)
    credit = max(0.0, short.mid - long_leg.mid)
    return (width - credit) * 100.0


def debit_vertical_loss(long_leg: ContractQuote, short: ContractQuote) -> float:
    """Estimated max loss in dollars for one debit vertical: the debit paid."""
    return max(0.0, long_leg.mid - short.mid) * 100.0


def select_credit_vertical(
    chain: OptionChain,
    expiry: date,
    right: Right,
    short_delta: float = 0.25,
    width_pct: float = DEFAULT_WIDTH_PCT,
    min_open_interest: int = 0,
    max_spread_pct: float = 1.0,
    budget: float | None = None,
) -> tuple[ContractQuote, ContractQuote] | None:
    """Pick ``(short, long)`` for a credit spread.

    Sell near ``short_delta``; place the long leg by BUDGET when one is given —
    the widest listed strike whose estimated max loss still fits the per-trade
    cap — and by width target otherwise. Out of the money means *lower* strikes
    for a put spread and *higher* for a call spread — the long leg is always the
    cheaper one, which is what makes the position a credit and caps the loss.

    Raises :class:`BudgetTooTight` when a budget is given and no listed interval
    fits it.
    """
    contracts = usable_contracts(chain, expiry, right, min_open_interest, max_spread_pct)
    if len(contracts) < 2:
        return None

    short = by_delta(contracts, short_delta)
    if short is None:
        return None

    direction = -1 if right == "PUT" else 1
    if budget is not None:
        long_leg = _walk_to_budget(contracts, short, direction, budget, credit_vertical_loss)
    else:
        long_leg = _walk_to_width(contracts, short, direction, target_width(chain.spot, width_pct))
    if long_leg is None:
        log.debug("no protective leg found for %s on %s", short.symbol, chain.symbol)
        return None
    return short, long_leg


def select_debit_vertical(
    chain: OptionChain,
    expiry: date,
    right: Right,
    long_delta: float = 0.50,
    width_pct: float = DEFAULT_WIDTH_PCT,
    min_open_interest: int = 0,
    max_spread_pct: float = 1.0,
    budget: float | None = None,
) -> tuple[ContractQuote, ContractQuote] | None:
    """Pick ``(long, short)`` for a debit spread.

    Buy near the money at ``long_delta``, then sell further out to reduce the
    cost. The debit paid is the maximum loss — wider means more debit, so with a
    budget the walk keeps the widest spread whose debit still fits.
    """
    contracts = usable_contracts(chain, expiry, right, min_open_interest, max_spread_pct)
    if len(contracts) < 2:
        return None

    long_leg = by_delta(contracts, long_delta)
    if long_leg is None:
        return None

    direction = 1 if right == "CALL" else -1
    if budget is not None:
        short = _walk_to_budget(contracts, long_leg, direction, budget, debit_vertical_loss)
    else:
        short = _walk_to_width(contracts, long_leg, direction, target_width(chain.spot, width_pct))
    if short is None:
        return None
    return long_leg, short


def select_condor_wings(
    chain: OptionChain,
    expiry: date,
    short_delta: float = 0.20,
    width_pct: float = DEFAULT_WIDTH_PCT,
    min_open_interest: int = 0,
    max_spread_pct: float = 1.0,
    budget: float | None = None,
) -> tuple[ContractQuote, ContractQuote, ContractQuote, ContractQuote] | None:
    """Pick ``(short_put, long_put, short_call, long_call)`` for an iron condor.

    A put credit spread and a call credit spread on the same expiry: the maximum
    expression of "volatility is overpriced and I do not care which way it goes".

    The budget is split across both wings per the sizing spec. This is
    conservative: only one wing can finish in the money, so a condor sized this
    way carries a true max loss of roughly HALF the per-trade cap.
    """
    wing_budget = budget / 2.0 if budget is not None else None
    put_side = select_credit_vertical(
        chain,
        expiry,
        "PUT",
        short_delta,
        width_pct,
        min_open_interest,
        max_spread_pct,
        budget=wing_budget,
    )
    call_side = select_credit_vertical(
        chain,
        expiry,
        "CALL",
        short_delta,
        width_pct,
        min_open_interest,
        max_spread_pct,
        budget=wing_budget,
    )
    if put_side is None or call_side is None:
        return None

    short_put, long_put = put_side
    short_call, long_call = call_side

    # The wings must not cross, or this is not a condor.
    if short_put.strike >= short_call.strike:
        log.debug(
            "condor wings cross on %s — short put %.2f >= short call %.2f",
            chain.symbol,
            short_put.strike,
            short_call.strike,
        )
        return None
    return short_put, long_put, short_call, long_call


def choose_expiry(
    chain: OptionChain,
    dte_min: int,
    dte_max: int,
    as_of: date | None = None,
    prefer_monthly: bool = True,
) -> date | None:
    """The best expiry inside the target DTE band.

    Prefers standard monthly expirations: they carry the deepest open interest
    and the tightest markets, which matters more to a real fill than landing on
    an exact DTE.
    """
    from skew.data.calendar import is_monthly_expiry

    ref = as_of or chain.as_of.date()
    window = chain.expiries_within(dte_min, dte_max, as_of=ref)
    if not window:
        return None

    if prefer_monthly:
        monthlies = [e for e in window if is_monthly_expiry(e)]
        if monthlies:
            return monthlies[0]

    midpoint = (dte_min + dte_max) / 2
    return min(window, key=lambda e: abs((e - ref).days - midpoint))
