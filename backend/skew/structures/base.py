"""Structure arithmetic: max loss, max profit, breakevens, net Greeks.

**Every structure knows its own maximum loss before it exists.** A structure
without a computed max loss is a bug, not an edge case — ``Structure`` refuses
to validate without a positive one, and every builder in this package routes
through :func:`assemble` so there is exactly one place that number is derived.

SIGN CONVENTIONS, stated once:

* ``net_credit`` is positive when money comes in, negative when it goes out.
* ``Leg.signed_ratio`` is +ratio for a long leg and −ratio for a short one, so
  a leg's cash contribution is ``−signed_ratio × mid × 100``.
* Net Greeks are per-contract share equivalents: ``Σ signed_ratio × greek × 100``.
  A short-premium structure therefore reports negative vega and positive theta,
  which is the whole point — we are a vega business.
* The mleg limit price inverts all of this again: **positive is a debit,
  negative is a credit.** That lives on ``Structure.limit_price`` and nowhere
  else.
"""

from __future__ import annotations

from datetime import date
from math import gcd
from typing import TYPE_CHECKING

from skew.models import (
    CONTRACT_MULTIPLIER,
    Leg,
    PositionIntent,
    Right,
    Side,
    Structure,
    StructureKind,
)

if TYPE_CHECKING:  # pragma: no cover
    from skew.data.chains import ContractQuote


class StructureError(ValueError):
    """A structure could not be built. Always carries a human-readable reason."""


# ----------------------------------------------------------------------
# Legs
# ----------------------------------------------------------------------


def leg_from_contract(
    contract: ContractQuote,
    side: Side,
    ratio_qty: int = 1,
    opening: bool = True,
) -> Leg:
    """Turn a chain quote into a structure leg.

    ``position_intent`` is required on every leg for an mleg order, and it is
    derived here rather than passed in so an opening order can never be tagged
    as a closing one.
    """
    # position_intent is required on every leg for an mleg order, and it is
    # derived rather than passed so an opening order cannot be tagged closing.
    intent: PositionIntent = {
        (True, "BUY"): "BTO",
        (True, "SELL"): "STO",
        (False, "BUY"): "BTC",
        (False, "SELL"): "STC",
    }[(opening, side)]

    if contract.mid <= 0:
        raise StructureError(
            f"{contract.symbol} has no usable price. Refusing to build a structure "
            f"around a contract we cannot value."
        )

    return Leg(
        symbol=contract.symbol,
        side=side,
        position_intent=intent,
        ratio_qty=ratio_qty,
        strike=contract.strike,
        expiry=contract.expiry,
        right=contract.right,
        mid=contract.mid,
        iv=contract.iv,
        delta=contract.delta,
        gamma=contract.gamma,
        theta=contract.theta,
        vega=contract.vega,
        bid=contract.bid,
        ask=contract.ask,
        open_interest=contract.open_interest,
        volume=contract.volume,
    )


def normalise_ratios(legs: list[Leg]) -> list[Leg]:
    """Divide every ratio by the GCD across legs.

    Alpaca rejects an mleg order whose leg ratios share a common factor: a 2:4
    spread must be sent as 1:2. This is cheap to get wrong and produces a
    rejection at submission time rather than at build time, so it is normalised
    the moment a structure is assembled.
    """
    if not legs:
        return legs
    divisor = 0
    for leg in legs:
        divisor = gcd(divisor, leg.ratio_qty)
    if divisor <= 1:
        return legs
    return [leg.model_copy(update={"ratio_qty": leg.ratio_qty // divisor}) for leg in legs]


# ----------------------------------------------------------------------
# Cash and Greeks
# ----------------------------------------------------------------------


def net_credit(legs: list[Leg], qty: int = 1) -> float:
    """Net cash for one submission. Positive = credit received."""
    return round(sum(-leg.signed_ratio * leg.mid * CONTRACT_MULTIPLIER for leg in legs) * qty, 4)


def net_greek(legs: list[Leg], name: str, qty: int = 1) -> float:
    """Per-contract share-equivalent net Greek across the legs."""
    return round(
        sum(leg.signed_ratio * getattr(leg, name) * CONTRACT_MULTIPLIER for leg in legs) * qty, 6
    )


def _vertical_width(legs: list[Leg], right: Right) -> float:
    strikes = sorted({leg.strike for leg in legs if leg.right == right})
    return (max(strikes) - min(strikes)) if len(strikes) >= 2 else 0.0


def _short_leg(legs: list[Leg], right: Right) -> Leg | None:
    """The short leg of one wing. For a credit spread this is the near strike."""
    shorts = [leg for leg in legs if leg.right == right and leg.side == "SELL"]
    if not shorts:
        return None
    # A put credit spread sells the higher strike; a call credit spread the lower.
    return (
        max(shorts, key=lambda leg: leg.strike)
        if right == "PUT"
        else min(shorts, key=lambda leg: leg.strike)
    )


def _long_leg(legs: list[Leg], right: Right) -> Leg | None:
    longs = [leg for leg in legs if leg.right == right and leg.side == "BUY"]
    if not longs:
        return None
    return (
        min(longs, key=lambda leg: leg.strike)
        if right == "PUT"
        else max(longs, key=lambda leg: leg.strike)
    )


def max_ratio(legs: list[Leg]) -> int:
    return max((leg.ratio_qty for leg in legs), default=1)


# ----------------------------------------------------------------------
# The risk numbers
# ----------------------------------------------------------------------


def compute_risk(
    kind: StructureKind, legs: list[Leg], credit: float, qty: int = 1
) -> tuple[float, float, list[float]]:
    """Return ``(max_loss, max_profit, breakevens)`` in dollars.

    Worked example from docs/04-OPTIONS-PRIMER.md §5 — a 580/575 put credit
    spread taken for $0.80::

        max profit = the $80 credit
        max loss   = (580 − 575) × 100 − 80 = $420
        breakeven  = 580 − 0.80 = 579.20

    Max loss is always returned positive.
    """
    ratio = max_ratio(legs)
    credit_per_share = credit / (CONTRACT_MULTIPLIER * qty) if qty else 0.0

    if kind in ("PUT_CREDIT", "CALL_CREDIT"):
        right: Right = "PUT" if kind == "PUT_CREDIT" else "CALL"
        width = _vertical_width(legs, right)
        short = _short_leg(legs, right)
        if width <= 0 or short is None:
            raise StructureError(f"{kind} needs a short leg and two distinct strikes.")
        if credit <= 0:
            raise StructureError(
                f"{kind} must be opened for a credit; got {credit:+.2f}. The short leg "
                f"is priced below the long one, which means the quotes are stale."
            )

        max_loss = width * CONTRACT_MULTIPLIER * ratio * qty - credit
        max_profit = credit
        breakeven = (
            short.strike - credit_per_share if right == "PUT" else short.strike + credit_per_share
        )
        return max_loss, max_profit, [round(breakeven, 4)]

    if kind in ("CALL_DEBIT", "PUT_DEBIT"):
        right = "CALL" if kind == "CALL_DEBIT" else "PUT"
        width = _vertical_width(legs, right)
        long_leg = _long_leg(legs, right)
        if width <= 0 or long_leg is None:
            raise StructureError(f"{kind} needs a long leg and two distinct strikes.")
        if credit >= 0:
            raise StructureError(f"{kind} must be opened for a debit; got {credit:+.2f}.")

        debit = -credit
        # The debit paid IS the maximum loss. That is what makes it defined risk.
        max_loss = debit
        max_profit = width * CONTRACT_MULTIPLIER * ratio * qty - debit
        debit_per_share = debit / (CONTRACT_MULTIPLIER * qty)
        breakeven = (
            long_leg.strike + debit_per_share
            if right == "CALL"
            else long_leg.strike - debit_per_share
        )
        return max_loss, max_profit, [round(breakeven, 4)]

    if kind == "IRON_CONDOR":
        put_width = _vertical_width(legs, "PUT")
        call_width = _vertical_width(legs, "CALL")
        short_put = _short_leg(legs, "PUT")
        short_call = _short_leg(legs, "CALL")
        if not (put_width > 0 and call_width > 0 and short_put and short_call):
            raise StructureError("An iron condor needs a complete put wing and call wing.")
        if credit <= 0:
            raise StructureError(f"An iron condor must be opened for a credit; got {credit:+.2f}.")

        # Only one wing can finish in the money, so the worst case is the wider
        # wing — not the sum of both.
        widest = max(put_width, call_width)
        max_loss = widest * CONTRACT_MULTIPLIER * ratio * qty - credit
        max_profit = credit
        return (
            max_loss,
            max_profit,
            [
                round(short_put.strike - credit_per_share, 4),
                round(short_call.strike + credit_per_share, 4),
            ],
        )

    raise StructureError(f"Unknown structure kind {kind!r}")


def structure_id(symbol: str, kind: StructureKind, expiry: date, legs: list[Leg]) -> str:
    """A readable, stable identifier.

    Deterministic rather than random so the same structure keeps its id across
    loop cycles — which is what lets the MCP ``stress_test(candidate_id)`` tool
    and the API's ``/api/stress/{id}`` refer to something durable, and what
    makes the audit log legible to a human.
    """
    strikes = "-".join(f"{leg.strike:g}" for leg in sorted(legs, key=lambda x: x.strike))
    return f"{symbol.upper()}:{kind}:{expiry:%y%m%d}:{strikes}"


def assemble(
    symbol: str,
    kind: StructureKind,
    legs: list[Leg],
    spot: float,
    qty: int = 1,
    as_of: date | None = None,
    max_loss_cap: float | None = None,
) -> Structure:
    """The single place a Structure comes into existence.

    Normalises ratios, computes the cash, derives max loss / max profit /
    breakevens, sums the Greeks, and lets ``Structure``'s own validators refuse
    anything with a non-positive max loss or a bad leg ratio.

    ``max_loss_cap`` is the construction-time budget assertion: the builders
    size their strikes to the risk budget, and this refuses any structure whose
    computed max loss exceeds it anyway — a sizing bug must die here, not reach
    the gate chain as noise.
    """
    if not 2 <= len(legs) <= 4:
        # Checked before the risk arithmetic so the diagnosis names the real
        # problem: "2–4 legs", not a downstream complaint about strikes.
        raise StructureError(f"Alpaca permits 2–4 legs for an mleg options order; got {len(legs)}.")

    legs = normalise_ratios(legs)
    credit = net_credit(legs, qty=qty)
    max_loss, max_profit, breakevens = compute_risk(kind, legs, credit, qty=qty)

    if max_loss <= 0:
        raise StructureError(
            f"Computed a non-positive max loss ({max_loss:.2f}) for {kind} on {symbol}. "
            f"Refusing to build a structure whose worst case is unknown."
        )
    if max_loss_cap is not None and max_loss > max_loss_cap:
        raise StructureError(
            f"Constructed {kind} on {symbol} with max loss ${max_loss:,.0f} above the "
            f"per-trade cap ${max_loss_cap:,.0f} — the builder sized its strikes wrong."
        )

    expiry = min(leg.expiry for leg in legs)
    ref = as_of or date.today()

    return Structure(
        id=structure_id(symbol, kind, expiry, legs),
        symbol=symbol.upper(),
        kind=kind,
        legs=legs,
        net_credit=round(credit, 2),
        max_loss=round(max_loss, 2),
        max_profit=round(max_profit, 2),
        breakevens=breakevens,
        net_delta=net_greek(legs, "delta", qty),
        net_vega=net_greek(legs, "vega", qty),
        net_theta=net_greek(legs, "theta", qty),
        net_gamma=net_greek(legs, "gamma", qty),
        dte=(expiry - ref).days,
        spot=spot,
        qty=qty,
    )
