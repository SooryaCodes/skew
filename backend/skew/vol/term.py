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

import itertools
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

# The default MATERIAL-inversion threshold: the front of the curve inverts
# routinely for idiosyncratic reasons (earnings drift, weekly supply) that have
# nothing to do with market stress. Only an inversion deeper than this blocks
# premium selling. Overridden per-desk via TERM_BACKWARDATION_FLOOR.
DEFAULT_BACKWARDATION_FLOOR = 0.015  # 1.5 vol points


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
    # Inversions shallower than this are noise, not stress. Set from
    # TERM_BACKWARDATION_FLOOR by the caller.
    backwardation_floor: float = DEFAULT_BACKWARDATION_FLOOR
    # OLS slope of IV on DTE, expressed per 30 days. Shape of the whole curve
    # rather than just its endpoints; reported as context.
    slope_per_30d: float = 0.0

    @property
    def is_backwardation(self) -> bool:
        """Materially inverted — beyond the floor, not merely negative."""
        return self.slope < -self.backwardation_floor

    @property
    def is_contango(self) -> bool:
        return self.slope > FLAT_TOLERANCE

    @property
    def shape(self) -> str:
        if self.is_backwardation:
            return "backwardation"
        return "contango" if self.is_contango else "flat"

    def describe(self) -> str:
        """Human copy for the UI and the gate reason string.

        Always names both measurement points and, when the curve is inverted,
        where the inversion sits against the tolerance — "inverted by 0.7
        points, inside the 1.5-point tolerance" is a pass, and says so.
        """
        if not self.points:
            return "term structure unavailable — fewer than two usable expiries"
        base = (
            f"{self.near_dte}d IV {self.near_iv * 100:.1f} vs "
            f"{self.far_dte}d IV {self.far_iv * 100:.1f}"
        )
        if self.slope < 0:
            relation = "beyond" if self.is_backwardation else "inside"
            return (
                f"{base} — inverted by {abs(self.slope) * 100:.1f} points, {relation} "
                f"the {self.backwardation_floor * 100:.1f}-point tolerance"
            )
        return f"{base} ({self.slope * 100:+.1f} vol points, contango)"


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


def interpolated_point(points: list[TermPoint], target_dte: int) -> tuple[int, float]:
    """IV at ``target_dte``, linearly interpolated between the bracketing
    expiries; clamped to the endpoints when the target sits outside the data.
    Returns (dte actually used, iv)."""
    if target_dte <= points[0].dte:
        return points[0].dte, points[0].iv_atm
    if target_dte >= points[-1].dte:
        return points[-1].dte, points[-1].iv_atm
    for lo, hi in itertools.pairwise(points):
        if lo.dte <= target_dte <= hi.dte:
            span = hi.dte - lo.dte
            t = 0.0 if span == 0 else (target_dte - lo.dte) / span
            return target_dte, lo.iv_atm + t * (hi.iv_atm - lo.iv_atm)
    return points[-1].dte, points[-1].iv_atm  # pragma: no cover


def term_structure_slope(
    chain: OptionChain,
    dte_min: int = 5,
    dte_max: int = 120,
    as_of: date | None = None,
    near_target_dte: int | None = None,
    far_target_dte: int | None = None,
    backwardation_floor: float = DEFAULT_BACKWARDATION_FLOOR,
) -> TermStructure | None:
    """Build the term structure. Returns None when fewer than two expiries are usable.

    None means "we do not know the shape of this curve", and every caller treats
    that as a reason to abstain — not as a zero slope.

    ``near_target_dte`` / ``far_target_dte`` pin the two measurement points:
    the tenor the desk actually trades (the middle of its entry window) against
    a meaningfully longer reference (60-90d). Without them the endpoints of the
    available window are used — which, after the move to short-dated entries,
    was measuring front-month noise and calling it stress.
    """
    points = term_points(chain, dte_min=dte_min, dte_max=dte_max, as_of=as_of)
    if len(points) < 2:
        return None

    if near_target_dte is not None:
        near_dte, near_iv = interpolated_point(points, near_target_dte)
    else:
        near_dte, near_iv = points[0].dte, points[0].iv_atm
    if far_target_dte is not None:
        far_dte, far_iv = interpolated_point(points, far_target_dte)
    else:
        far_dte, far_iv = points[-1].dte, points[-1].iv_atm

    slope = far_iv - near_iv

    dtes = np.array([p.dte for p in points], dtype=float)
    ivs = np.array([p.iv_atm for p in points], dtype=float)
    per_30d = 0.0
    if np.ptp(dtes) > 0:
        per_30d = float(np.polyfit(dtes, ivs, 1)[0] * 30.0)

    return TermStructure(
        symbol=chain.symbol,
        points=points,
        near_iv=near_iv,
        far_iv=far_iv,
        near_dte=near_dte,
        far_dte=far_dte,
        slope=slope,
        slope_per_30d=per_30d,
        backwardation_floor=backwardation_floor,
    )


def is_backwardation(structure: TermStructure | None) -> bool:
    """True only when we *know* the curve is inverted.

    An unknown curve is not backwardation — it is handled separately, and more
    conservatively, by the gate.
    """
    return structure is not None and structure.is_backwardation
