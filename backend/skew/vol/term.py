"""Term structure: contango or backwardation.

Plot ATM implied volatility against expiration date.

* **Contango** — further-out options carry higher IV. Normal. Calm market.
* **Backwardation** — near-term IV above long-dated. The market is scared *right
  now*.

This is the input to the hardest gate in the system. Selling volatility into
backwardation is the single most reliable way to blow up an options account, so
``skew/gates/term_structure.py`` blocks every premium-selling structure whenever
this module reports an inverted curve. See docs/04-OPTIONS-PRIMER.md §6.

All IVs are annualised decimals (0.241 = 24.1%).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import numpy as np
from pydantic import BaseModel, Field

from skew.models import TermPoint

if TYPE_CHECKING:  # pragma: no cover
    from skew.data.chains import OptionChain

# A curve inside this band is flat, not inverted. Quote noise on a single
# expiry should not read as market panic.
FLAT_TOLERANCE = 0.005  # half a vol point


class TermStructure(BaseModel):
    """The ATM IV curve across expirations, and what it implies."""

    symbol: str
    points: list[TermPoint] = Field(default_factory=list)
    near_iv: float = 0.0
    far_iv: float = 0.0
    near_dte: int = 0
    far_dte: int = 0
    # far_iv − near_iv, in annualised decimals. Positive = contango.
    slope: float = 0.0
    # OLS slope of IV on DTE, expressed per 30 days. Shape of the whole curve
    # rather than just its endpoints; reported as context.
    slope_per_30d: float = 0.0

    @property
    def is_backwardation(self) -> bool:
        return self.slope < -FLAT_TOLERANCE

    @property
    def is_contango(self) -> bool:
        return self.slope > FLAT_TOLERANCE

    @property
    def shape(self) -> str:
        if self.is_backwardation:
            return "backwardation"
        return "contango" if self.is_contango else "flat"

    def describe(self) -> str:
        """Human copy for the UI and the gate reason string."""
        if not self.points:
            return "term structure unavailable — fewer than two usable expiries"
        return (
            f"{self.shape}: {self.near_dte}d IV {self.near_iv * 100:.1f} vs "
            f"{self.far_dte}d IV {self.far_iv * 100:.1f} "
            f"({self.slope * 100:+.1f} vol points)"
        )


def term_points(
    chain: OptionChain,
    dte_min: int = 5,
    dte_max: int = 120,
    as_of: date | None = None,
) -> list[TermPoint]:
    """ATM IV at every usable expiry in the window, nearest first."""
    from skew.vol.implied import atm_implied_vol

    ref = as_of or chain.as_of.date()
    out: list[TermPoint] = []
    for expiry in chain.expiries:
        days = (expiry - ref).days
        if not (dte_min <= days <= dte_max):
            continue
        atm = atm_implied_vol(chain, expiry=expiry, as_of=ref)
        if atm is None or atm.iv <= 0:
            continue
        out.append(TermPoint(expiry=expiry, dte=days, iv_atm=atm.iv))
    return sorted(out, key=lambda p: p.dte)


def term_structure_slope(
    chain: OptionChain,
    dte_min: int = 5,
    dte_max: int = 120,
    as_of: date | None = None,
) -> TermStructure | None:
    """Build the term structure. Returns None when fewer than two expiries are usable.

    None means "we do not know the shape of this curve", and every caller treats
    that as a reason to abstain — not as a zero slope.
    """
    points = term_points(chain, dte_min=dte_min, dte_max=dte_max, as_of=as_of)
    if len(points) < 2:
        return None

    near, far = points[0], points[-1]
    slope = far.iv_atm - near.iv_atm

    dtes = np.array([p.dte for p in points], dtype=float)
    ivs = np.array([p.iv_atm for p in points], dtype=float)
    per_30d = 0.0
    if np.ptp(dtes) > 0:
        per_30d = float(np.polyfit(dtes, ivs, 1)[0] * 30.0)

    return TermStructure(
        symbol=chain.symbol,
        points=points,
        near_iv=near.iv_atm,
        far_iv=far.iv_atm,
        near_dte=near.dte,
        far_dte=far.dte,
        slope=slope,
        slope_per_30d=per_30d,
    )


def is_backwardation(structure: TermStructure | None) -> bool:
    """True only when we *know* the curve is inverted.

    An unknown curve is not backwardation — it is handled separately, and more
    conservatively, by the gate.
    """
    return structure is not None and structure.is_backwardation
