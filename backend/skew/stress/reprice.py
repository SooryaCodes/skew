"""Black-Scholes repricing for the stress engine.

**This is the one place in the codebase that implements Black-Scholes**, and the
distinction matters. Everywhere else we read implied volatility and Greeks
straight off the Alpaca snapshot, because those are market observations and
re-deriving them would introduce error. Here we are pricing a *hypothetical* —
"what is this structure worth if the underlying gaps 2σ against us and implied
vol doubles, halfway to expiry" — and no endpoint will answer that. So we price
it ourselves.

THE CLASSIC BUG, stated so it stays fixed: **time to expiry must be in years.**
Passing days produces prices that look plausible and are wrong by an order of
magnitude, and it is the single most common error in an options codebase. Every
function here takes ``years`` and the conversion happens at one boundary.

Sigma is an annualised decimal, matching ``skew.vol.realized``.
"""

from __future__ import annotations

import math
from typing import Literal

from skew.models import CONTRACT_MULTIPLIER, Leg, Structure

Right = Literal["CALL", "PUT"]

# Under this many years to expiry, discounting and time value are immaterial and
# the numerically stable answer is intrinsic value.
MIN_YEARS = 1e-9


def norm_cdf(x: float) -> float:
    """Standard normal CDF via the error function. No SciPy needed, and exact."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def intrinsic_value(spot: float, strike: float, right: Right) -> float:
    return max(0.0, spot - strike) if right == "CALL" else max(0.0, strike - spot)


def bs_price(
    spot: float,
    strike: float,
    years: float,
    vol: float,
    right: Right,
    rate: float = 0.042,
) -> float:
    """Black-Scholes price of one European option, per share.

    ``years`` is time to expiry in YEARS. ``vol`` is annualised, as a decimal.

    Degenerate inputs — no time left, no volatility — collapse to intrinsic
    value rather than producing a NaN, because the stress grid deliberately
    evaluates the expiry column and a NaN there would silently poison the worst
    case that the whole gate depends on.
    """
    if spot <= 0 or strike <= 0:
        return 0.0
    if years <= MIN_YEARS or vol <= 0:
        return intrinsic_value(spot, strike, right)

    sqrt_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    discount = math.exp(-rate * years)

    if right == "CALL":
        return spot * norm_cdf(d1) - strike * discount * norm_cdf(d2)
    return strike * discount * norm_cdf(-d2) - spot * norm_cdf(-d1)


def bs_delta(
    spot: float, strike: float, years: float, vol: float, right: Right, rate: float = 0.042
) -> float:
    """Delta, for context on the shocked position. Never used for selection."""
    if years <= MIN_YEARS or vol <= 0 or spot <= 0 or strike <= 0:
        if right == "CALL":
            return 1.0 if spot > strike else 0.0
        return -1.0 if spot < strike else 0.0

    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * years) / (vol * math.sqrt(years))
    return norm_cdf(d1) if right == "CALL" else norm_cdf(d1) - 1.0


def leg_value(
    leg: Leg,
    spot: float,
    years: float,
    iv_multiplier: float = 1.0,
    rate: float = 0.042,
    qty: int = 1,
) -> float:
    """Signed dollar value of one leg under shocked inputs.

    Positive for a long leg (an asset), negative for a short leg (a liability),
    so the legs of a structure simply sum.
    """
    price = bs_price(spot, leg.strike, years, leg.iv * iv_multiplier, leg.right, rate)
    return leg.signed_ratio * price * CONTRACT_MULTIPLIER * qty


def structure_value(
    structure: Structure,
    spot: float,
    years: float,
    iv_multiplier: float = 1.0,
    rate: float = 0.042,
) -> float:
    """Net liquidation value of the whole structure under shocked inputs.

    Negative for a credit structure that still carries risk — we owe more than
    we hold — which is exactly why the P&L below adds the credit back.
    """
    return sum(
        leg_value(leg, spot, years, iv_multiplier, rate, structure.qty) for leg in structure.legs
    )


def entry_value(structure: Structure) -> float:
    """What the position was worth the moment it was opened.

    Identically ``−net_credit``: taking in $80 of credit means the position
    starts as an $80 liability. Computed from the legs rather than asserted, so
    a sign error anywhere upstream shows up here as a mismatch.
    """
    return sum(
        leg.signed_ratio * leg.mid * CONTRACT_MULTIPLIER * structure.qty for leg in structure.legs
    )


def structure_pnl(
    structure: Structure,
    spot: float,
    years: float,
    iv_multiplier: float = 1.0,
    rate: float = 0.042,
) -> float:
    """Profit or loss versus the entry price, in dollars.

    Worked through on the primer's 580/575 put credit spread taken for $80:

    * Both puts expire worthless -> value 0, P&L = 0 − (−80) = **+$80**, the
      max profit.
    * Underlying at 570 at expiry -> short put worth $10, long worth $5, value
      = (−10 + 5) × 100 = −$500, P&L = −500 + 80 = **−$420**, the max loss.
    """
    return structure_value(structure, spot, years, iv_multiplier, rate) - entry_value(structure)


def expiry_pnl(structure: Structure, spot: float) -> float:
    """P&L at expiry — intrinsic values only, no time value and no discounting."""
    value = sum(
        leg.signed_ratio
        * intrinsic_value(spot, leg.strike, leg.right)
        * CONTRACT_MULTIPLIER
        * structure.qty
        for leg in structure.legs
    )
    return value - entry_value(structure)
