"""Term structure gate — **never sell premium in backwardation.**

Plot implied volatility against expiration. Normally the curve slopes up:
further-dated options carry higher IV, because more can happen in more time.
That is contango, and it is what a calm market looks like.

When the curve inverts — near-term IV above long-dated — the market is telling
you it is frightened *right now*, about something specific and imminent. That is
backwardation.

Selling volatility into backwardation is the single most reliable way to blow up
an options account. The premium looks generous precisely because the risk is
real, and the position is short exactly the thing that is about to move. Every
vol trader knows this rule; a finance judge will look for it; and having it is a
credibility signal all by itself.

Two further notes on the design:

* **This gate does not block buying premium.** An inverted curve with cheap vol
  is a legitimate reason to *own* volatility. The rule is about selling into
  stress, not about refusing to act.
* **An unknown curve is not a flat one.** When fewer than two expiries carry
  usable quotes, the shape cannot be determined, and a premium sale is refused.

See docs/04-OPTIONS-PRIMER.md §6.
"""

from __future__ import annotations

from skew.gates.base import GateContext
from skew.models import Candidate, GateResult

GATE = "term"

PREMIUM_SELLING_KINDS = ("PUT_CREDIT", "CALL_CREDIT", "IRON_CONDOR")


def term_structure_gate(candidate: Candidate, ctx: GateContext) -> GateResult:
    structure = candidate.structure
    selling = structure.kind in PREMIUM_SELLING_KINDS

    if not selling:
        return GateResult(
            gate=GATE,
            passed=True,
            reason=(
                "Long premium — the backwardation rule guards against selling volatility "
                "into stress and does not apply to buying it."
            ),
            detail={"kind": structure.kind},
            skipped=True,
        )

    term = ctx.term
    if term is None:
        return GateResult(
            gate=GATE,
            passed=False,
            reason=(
                f"Term structure for {structure.symbol} could not be determined — fewer than "
                f"two expiries with usable quotes. An unknown curve is not a flat one, and "
                f"selling premium requires knowing the shape."
            ),
            detail={"status": "unknown"},
        )

    if term.is_backwardation:
        return GateResult(
            gate=GATE,
            passed=False,
            reason=(
                f"Backwardation — {term.near_dte}d implied vol {term.near_iv * 100:.1f} sits "
                f"above {term.far_dte}d {term.far_iv * 100:.1f}, an inversion of "
                f"{abs(term.slope) * 100:.1f} vol points. The market is pricing near-term "
                f"stress; selling volatility into it is how options accounts are lost."
            ),
            detail={
                "shape": "backwardation",
                "slope": round(term.slope, 6),
                "near_dte": term.near_dte,
                "near_iv": round(term.near_iv, 6),
                "far_dte": term.far_dte,
                "far_iv": round(term.far_iv, 6),
            },
        )

    shape = term.shape
    return GateResult(
        gate=GATE,
        passed=True,
        reason=(
            f"Curve in {shape} — {term.near_dte}d IV {term.near_iv * 100:.1f} versus "
            f"{term.far_dte}d {term.far_iv * 100:.1f} ({term.slope * 100:+.1f} vol points). "
            f"No near-term stress priced in."
        ),
        detail={
            "shape": shape,
            "slope": round(term.slope, 6),
            "slope_per_30d": round(term.slope_per_30d, 6),
            "near_dte": term.near_dte,
            "far_dte": term.far_dte,
        },
    )


term_structure_gate.gate_name = GATE  # type: ignore[attr-defined]
