"""The gate chain.

Every gate is a pure function of a candidate and a context, returning a
``GateResult(passed, reason, detail)``. The ``reason`` string is rendered
**verbatim** in the UI, so it is written here as human copy with real numbers in
it — "worst case −$1,240 at −2σ with IV +100%, exceeds tier budget $1,000", not
"stress check failed".

**The runner evaluates every gate even after one fails.** That is deliberate and
it is a product decision, not an implementation detail: the interface shows the
full picture of why a trade was refused, not just the first thing that went
wrong. A judge watching the demo sees liquidity ✓, earnings ✓, term ✓, stress ✗,
budget ✓ — which says something quite different from "stress ✗" alone.

A gate that raises is treated as a failure with the exception text in the
reason. A risk check that errors is not a risk check that passed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING

from skew.models import Candidate, GateResult, RiskAuthority, VolState

if TYPE_CHECKING:  # pragma: no cover
    from skew.data.calendar import EarningsCalendar
    from skew.vol.term import TermStructure

log = logging.getLogger(__name__)


@dataclass
class GateContext:
    """Everything the gates need, gathered once per symbol per cycle.

    Passed as one object so a new gate can be added without changing the
    signature of the runner or of every existing gate.
    """

    vol_state: VolState
    risk: RiskAuthority
    realized_vol: float
    term: TermStructure | None = None
    earnings: EarningsCalendar | None = None
    as_of: date = field(default_factory=lambda: datetime.now().date())

    # Thresholds, snapshotted from settings so a gate result can be reproduced
    # from the audit log even if config later changes.
    min_open_interest: int = 100
    max_spread_pct: float = 0.15
    min_volume: int = 0
    earnings_blackout_days: int = 7
    earnings_unknown_blocks: bool = True
    risk_free_rate: float = 0.042
    # The routine-move check: a move of this many sigma must not already consume
    # more than this fraction of the budget. See skew/gates/stress.py.
    routine_sigma: float = 1.0
    routine_max_loss_pct: float = 0.60
    open_positions: int = 0
    max_concurrent_positions: int = 3


Gate = Callable[[Candidate, GateContext], GateResult]


def skipped(gate: str, reason: str) -> GateResult:
    """A gate that does not apply. Renders as "—" and never blocks."""
    return GateResult(gate=gate, passed=True, reason=reason, skipped=True)


def run_gates(
    candidate: Candidate,
    context: GateContext,
    gates: list[Gate] | None = None,
) -> Candidate:
    """Run the full chain and attach every result to the candidate.

    Order matches the architecture doc: liquidity → earnings → term structure →
    stress → budget. It is the order a human would check them in, cheapest and
    most disqualifying first, and it is the order the UI renders.
    """
    chain = gates if gates is not None else default_gates()
    results: list[GateResult] = []

    for gate in chain:
        name = getattr(gate, "gate_name", gate.__name__)
        try:
            results.append(gate(candidate, context))
        except Exception as exc:
            log.exception("gate %s raised on %s", name, candidate.id)
            results.append(
                GateResult(
                    gate=name,
                    passed=False,
                    reason=(
                        f"Gate could not be evaluated: {exc}. Treating as a failure — "
                        f"a risk check that errors is not a risk check that passed."
                    ),
                    detail={"exception": type(exc).__name__},
                )
            )

    candidate.gates = results
    candidate.recompute_passed()
    return candidate


def default_gates() -> list[Gate]:
    """The standard chain, in evaluation order."""
    from skew.gates.budget import budget_gate
    from skew.gates.earnings import earnings_gate
    from skew.gates.liquidity import liquidity_gate
    from skew.gates.stress import stress_gate
    from skew.gates.term_structure import term_structure_gate

    return [
        liquidity_gate,
        earnings_gate,
        term_structure_gate,
        stress_gate,
        budget_gate,
    ]


def summarise(candidate: Candidate) -> str:
    """One-line summary for the audit log.

    Names every failing gate, not just the first, so the log entry carries the
    same full picture the UI shows.
    """
    failed = candidate.failed_gates
    if not failed:
        return "passed all gates"
    if len(failed) == 1:
        return failed[0].reason
    heads = "; ".join(f"{g.gate}: {g.reason}" for g in failed)
    return f"failed {len(failed)} gates — {heads}"
