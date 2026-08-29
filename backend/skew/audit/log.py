"""The append-only decision log.

**Refusals and abstentions are recorded exactly as prominently as executions.**
That is not a logging preference; it is the product. A system that only records
what it did tells you nothing about its judgement. A system that records every
trade it declined, with the specific failing condition and the numbers behind
it, can be audited by someone who has never seen the code.

Append-only is enforced by the shape of this module: there is a ``record``, and
there are readers. No update path and no delete path exists anywhere in the
codebase, so a decision cannot be quietly revised after the fact.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from skew.audit.models import DecisionRow
from skew.db import session_scope
from skew.models import Candidate, Decision, DecisionAction

log = logging.getLogger(__name__)


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _to_model(row: DecisionRow) -> Decision:
    ts = row.ts if row.ts.tzinfo else row.ts.replace(tzinfo=UTC)
    return Decision(
        id=row.id,
        ts=ts,
        action=row.action,
        symbol=row.symbol,
        structure_id=row.structure_id,
        reason=row.reason,
        model_rationale=row.model_rationale,
        risk_tier=row.risk_tier,
        order_id=row.order_id,
        detail=row.detail or {},
    )


def record(
    action: DecisionAction,
    reason: str,
    risk_tier: int,
    symbol: str | None = None,
    structure_id: str | None = None,
    model_rationale: str | None = None,
    order_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> Decision:
    """Append one decision. Never updates, never deletes."""
    decision = Decision(
        id=_new_id(),
        ts=datetime.now(UTC),
        action=action,
        symbol=symbol,
        structure_id=structure_id,
        reason=reason,
        model_rationale=model_rationale,
        risk_tier=risk_tier,
        order_id=order_id,
        detail=detail or {},
    )

    with session_scope() as session:
        session.add(
            DecisionRow(
                id=decision.id,
                ts=decision.ts,
                action=decision.action,
                symbol=decision.symbol,
                structure_id=decision.structure_id,
                reason=decision.reason,
                model_rationale=decision.model_rationale,
                risk_tier=decision.risk_tier,
                order_id=decision.order_id,
                detail=decision.detail,
            )
        )

    log.info("[%s] %s — %s", decision.action, decision.symbol or "—", decision.reason)
    return decision


def record_refusal(candidate: Candidate, risk_tier: int, extra: dict[str, Any] | None = None):
    """Log a candidate the gate chain refused, with every gate result attached.

    The full chain is stored, not just the failing gate, so the log carries the
    same complete picture the UI shows — liquidity ✓, earnings ✓, term ✓,
    stress ✗, budget ✓ says something quite different from "stress ✗".
    """
    from skew.gates.base import summarise

    detail: dict[str, Any] = {
        "gates": [g.model_dump() for g in candidate.gates],
        "worst_case": candidate.worst_case,
        "max_loss": candidate.structure.max_loss,
        "net_credit": candidate.structure.net_credit,
        "kind": candidate.structure.kind,
        "failed": [g.gate for g in candidate.failed_gates],
    }
    # A refusal with a genuine breach keeps its whole grid. That is the moment
    # the product exists for, and it must be exhibitable later — the landing
    # page shows a real refused grid, never a mocked one.
    if any(cell.breached for cell in candidate.stress_grid):
        detail["stress_grid"] = [cell.model_dump() for cell in candidate.stress_grid]
    if extra:
        detail.update(extra)

    return record(
        action="REFUSED",
        reason=summarise(candidate),
        risk_tier=risk_tier,
        symbol=candidate.structure.symbol,
        structure_id=candidate.structure.id,
        detail=detail,
    )


def record_abstention(
    symbol: str | None,
    reason: str,
    risk_tier: int,
    model_rationale: str | None = None,
    detail: dict[str, Any] | None = None,
):
    return record(
        action="ABSTAINED",
        reason=reason,
        risk_tier=risk_tier,
        symbol=symbol,
        model_rationale=model_rationale,
        detail=detail,
    )


def record_execution(
    candidate: Candidate,
    risk_tier: int,
    order_id: str,
    model_rationale: str | None = None,
    detail: dict[str, Any] | None = None,
):
    structure = candidate.structure
    body: dict[str, Any] = {
        "gates": [g.model_dump() for g in candidate.gates],
        "kind": structure.kind,
        "legs": [leg.symbol for leg in structure.legs],
        "net_credit": structure.net_credit,
        "max_loss": structure.max_loss,
        "worst_case": candidate.worst_case,
        "limit_price": structure.limit_price,
    }
    if detail:
        body.update(detail)

    return record(
        action="EXECUTED",
        reason=(
            f"Submitted {structure.describe()} for a "
            f"{'credit' if structure.is_credit else 'debit'} of "
            f"${abs(structure.net_credit):,.2f}, max loss ${structure.max_loss:,.2f}."
        ),
        risk_tier=risk_tier,
        symbol=structure.symbol,
        structure_id=structure.id,
        model_rationale=model_rationale,
        order_id=order_id,
        detail=body,
    )


# ------------------------------------------------------------------ readers


def recent(limit: int = 50, action: DecisionAction | None = None) -> list[Decision]:
    """Newest first."""
    with session_scope() as session:
        query = select(DecisionRow).order_by(DecisionRow.ts.desc()).limit(max(1, min(limit, 500)))
        if action:
            query = query.where(DecisionRow.action == action)
        return [_to_model(r) for r in session.scalars(query).all()]


def for_symbol(symbol: str, limit: int = 50) -> list[Decision]:
    with session_scope() as session:
        rows = session.scalars(
            select(DecisionRow)
            .where(DecisionRow.symbol == symbol.upper())
            .order_by(DecisionRow.ts.desc())
            .limit(limit)
        ).all()
    return [_to_model(r) for r in rows]


def by_id(decision_id: str) -> Decision | None:
    with session_scope() as session:
        row = session.get(DecisionRow, decision_id)
        return _to_model(row) if row else None


def counts_since(moment: datetime) -> dict[str, int]:
    """Executions, refusals and abstentions since a specific instant."""
    with session_scope() as session:
        rows = session.execute(
            select(DecisionRow.action, func.count(DecisionRow.id))
            .where(DecisionRow.ts >= moment)
            .group_by(DecisionRow.action)
        ).all()
    out = {"EXECUTED": 0, "REFUSED": 0, "ABSTAINED": 0}
    for action, count in rows:
        out[action] = int(count)
    out["TOTAL"] = sum(v for k, v in out.items() if k != "TOTAL")
    return out


def counts(since_hours: int | None = None) -> dict[str, int]:
    """Executions, refusals and abstentions.

    Surfaced in the UI because the ratio is the honest headline: a desk that
    refused forty times and traded twice is doing its job.
    """
    with session_scope() as session:
        query = select(DecisionRow.action, func.count(DecisionRow.id)).group_by(DecisionRow.action)
        if since_hours:
            query = query.where(DecisionRow.ts >= datetime.now(UTC) - timedelta(hours=since_hours))
        rows = session.execute(query).all()

    out = {"EXECUTED": 0, "REFUSED": 0, "ABSTAINED": 0}
    for action, count in rows:
        out[action] = int(count)
    out["TOTAL"] = sum(v for k, v in out.items() if k != "TOTAL")
    return out
