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


def _order_filled(order_id: str | None) -> bool | None:
    """Fill state of the linked order: True filled, False dead unfilled,
    None resting/unknown/no order."""
    if not order_id:
        return None
    from skew.audit.models import OrderRow

    with session_scope() as session:
        row = session.get(OrderRow, order_id)
    if row is None:
        return None
    status = (row.status or "").lower()
    if status == "filled":
        return True
    if status in {"expired", "canceled", "cancelled", "rejected", "replaced", "done_for_day"}:
        return False
    return None


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
        order_filled=_order_filled(row.order_id) if row.action == "EXECUTED" else None,
        detail=row.detail or {},
    )


def connected_account() -> str:
    """The account this process is writing decisions for. Empty until the boot
    check has identified it — decision histories are never mixed across
    accounts (see the boot-time guard in api.py)."""
    from skew import loop

    return str(loop.ACCOUNT.get("number") or "")


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
                account=connected_account(),
            )
        )

    log.info("[%s] %s — %s", decision.action, decision.symbol or "—", decision.reason)
    return decision


def record_refusal(
    candidate: Candidate,
    risk_tier: int,
    extra: dict[str, Any] | None = None,
    trace: dict[str, Any] | None = None,
):
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
    if trace:
        detail["trace"] = trace

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
    trace: dict[str, Any] | None = None,
):
    body = dict(detail or {})
    if trace:
        body["trace"] = trace
    return record(
        action="ABSTAINED",
        reason=reason,
        risk_tier=risk_tier,
        symbol=symbol,
        model_rationale=model_rationale,
        detail=body,
    )


def record_execution(
    candidate: Candidate,
    risk_tier: int,
    order_id: str,
    model_rationale: str | None = None,
    detail: dict[str, Any] | None = None,
    trace: dict[str, Any] | None = None,
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
    if trace:
        body["trace"] = trace

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


# ------------------------------------------------------------ config markers

# The parameters whose changes are recorded in the audit log. When one moves,
# historical entries citing the old value stay exactly as written — a true
# record of the prior configuration — and a CONFIG entry marks the boundary
# so the two eras never read as a contradiction.
WATCHED_PARAMS = (
    "max_concurrent_positions",
    "profit_target_pct",
    "loss_limit_multiple",
    "exit_dte_threshold",
    "drawdown_breaker_pct",
)

# Values as they stood before config tracking existed, so the first diff on a
# pre-existing history is detected rather than silently baselined away.
_PRE_TRACKING_BASELINE = {
    "max_concurrent_positions": 3,
    "profit_target_pct": 0.45,
    "loss_limit_multiple": 2.0,
    "exit_dte_threshold": 2,
    "drawdown_breaker_pct": 0.05,
}

_CONFIG_SNAPSHOT_KEY = "config_snapshot"


def _describe_change(param: str, old: Any, new: Any) -> str:
    if param == "max_concurrent_positions":
        verb = "raised" if new > old else "lowered"
        return (
            f"Position limit {verb} from {old} to {new}. The portfolio cap is "
            f"unchanged and remains the binding exposure limit. Refusals recorded "
            f"before this timestamp cite the prior limit."
        )
    if param == "profit_target_pct":
        return (
            f"Profit target moved from {old:.0%} to {new:.0%} of credit — the "
            f"competition window is days rather than weeks, so the desk takes "
            f"profit earlier than it would on a normal horizon."
        )
    if param == "loss_limit_multiple":
        return f"Loss limit moved from {old:g}x to {new:g}x the opening premium."
    return f"{param} changed from {old} to {new}."


def record_correction(
    reason: str, symbol: str | None = None, detail: dict[str, Any] | None = None
) -> Decision:
    """A reconciliation correction: the record diverged from the broker and
    this entry says exactly how. Appended, never replacing anything — the
    original wrong entry stays visible above it. That is deliberate: a dated
    correction is the strongest evidence the log is real."""
    body = dict(detail or {})
    body["correction"] = True
    return record(action="CORRECTION", reason=reason, risk_tier=0, symbol=symbol, detail=body)


def record_config_change(reason: str, changes: list[dict[str, Any]]) -> Decision:
    """One system-level CONFIG entry. Rendered as an era divider in the UI,
    never counted or filtered as a trading decision."""
    return record(
        action="CONFIG",
        reason=reason,
        risk_tier=0,
        detail={"config_change": True, "changes": changes},
    )


def record_config_changes_at_boot(settings: Any) -> Decision | None:
    """Compare the running configuration to the stored snapshot; write one
    CONFIG entry naming every watched parameter that moved, then store the new
    snapshot. A fresh database is baselined silently — there is no prior era
    to divide from."""
    from sqlalchemy import func as sa_func

    from skew.audit.models import KVRow

    current = {p: getattr(settings, p) for p in WATCHED_PARAMS}
    with session_scope() as session:
        row = session.get(KVRow, _CONFIG_SNAPSHOT_KEY)
        if row is not None:
            prior = dict(row.value)
        else:
            decisions_exist = (
                session.execute(select(sa_func.count(DecisionRow.id))).scalar_one() > 0
            )
            prior = dict(_PRE_TRACKING_BASELINE) if decisions_exist else None
        if row is None:
            session.add(KVRow(key=_CONFIG_SNAPSHOT_KEY, value=current))
        else:
            row.value = current

    if prior is None:
        return None
    changes = [
        {"param": p, "old": prior.get(p), "new": current[p]}
        for p in WATCHED_PARAMS
        if p in prior and prior.get(p) != current[p]
    ]
    if not changes:
        return None
    reason = " ".join(_describe_change(c["param"], c["old"], c["new"]) for c in changes)
    return record_config_change(reason, changes)


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


def filled_order_ids(session) -> set[str]:
    """Client order ids the broker actually FILLED (reconciled each cycle).
    The fills counter counts these, not submissions — an EXECUTED entry whose
    order expired unfilled is a submission record, not a fill."""
    from skew.audit.models import OrderRow

    rows = session.execute(
        select(OrderRow.client_order_id).where(OrderRow.status == "filled")
    ).all()
    return {cid for (cid,) in rows}


def counts_since(moment: datetime) -> dict[str, int]:
    """Executions, refusals and abstentions since a specific instant."""
    with session_scope() as session:
        rows = session.execute(
            select(DecisionRow.action, func.count(DecisionRow.id))
            .where(DecisionRow.ts >= moment)
            .group_by(DecisionRow.action)
        ).all()
        filled = filled_order_ids(session)
        executed_filled = (
            session.execute(
                select(func.count(DecisionRow.id)).where(
                    DecisionRow.ts >= moment,
                    DecisionRow.action == "EXECUTED",
                    DecisionRow.order_id.in_(filled) if filled else DecisionRow.order_id.is_(None),
                )
            ).scalar_one()
            if filled
            else 0
        )
    out = {"EXECUTED": 0, "REFUSED": 0, "ABSTAINED": 0}
    for action, count in rows:
        if action in out:  # CONFIG/CORRECTION markers are not decisions
            out[action] = int(count)
    # Fills are fills: only submissions the broker confirmed filled count.
    out["EXECUTED"] = int(executed_filled)
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
        filled = filled_order_ids(session)
        fill_query = select(func.count(DecisionRow.id)).where(
            DecisionRow.action == "EXECUTED",
            DecisionRow.order_id.in_(filled) if filled else DecisionRow.order_id.is_(None),
        )
        if since_hours:
            fill_query = fill_query.where(
                DecisionRow.ts >= datetime.now(UTC) - timedelta(hours=since_hours)
            )
        executed_filled = session.execute(fill_query).scalar_one() if filled else 0

    out = {"EXECUTED": 0, "REFUSED": 0, "ABSTAINED": 0}
    for action, count in rows:
        if action in out:  # CONFIG/CORRECTION markers are not decisions
            out[action] = int(count)
    # Fills are fills: only submissions the broker confirmed filled count.
    out["EXECUTED"] = int(executed_filled)
    out["TOTAL"] = sum(v for k, v in out.items() if k != "TOTAL")
    return out
