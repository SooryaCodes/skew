"""Query layer for the full decision record (/audit page).

The stream readers in ``log.py`` answer "what happened lately"; this module
answers "show me everything, filtered, and make 2,000 rows legible". Three
jobs, all pure functions over loaded rows so they test without a network:

1. **Filter** — outcome, symbols, failing gate, free text, date range.
2. **Group** — runs of decisions sharing (outcome, reason template) collapse
   into one item with a count and a time range. The desk's cycles interleave
   refusals with abstentions, so *strictly* consecutive runs break every two
   or three rows and teach nothing; instead a run stays open until a FILL
   appears in the stream. Fills are rare, never collapse, and act as honest
   chronological anchors — nothing is grouped across one.
3. **Aggregate** — the summary panel: refusals by gate, decisions per day,
   the most-refused symbol. Computed from the *filtered* set, so the panel
   always describes exactly what the table shows.

Nothing here writes. The log stays append-only.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select

from skew.audit.models import DecisionRow
from skew.db import session_scope

# Mirrors reasonTemplate() in the frontend rail: mask tickers, dollars, counts
# and percentages so sentences that differ only in their particulars share a
# template, while a genuinely different sentence never matches.
_TICKER = re.compile(r"[A-Z][A-Z.]{1,5}")
_NUMBER = re.compile(r"[−-]?\$?\d[\d,]*(\.\d+)?%?")
_SPACE = re.compile(r"\s+")


def reason_template(reason: str) -> str:
    masked = _TICKER.sub("#", reason)
    masked = _NUMBER.sub("#", masked)
    return _SPACE.sub(" ", masked).strip()


def template_hash(reason: str) -> str:
    return hashlib.md5(reason_template(reason).encode()).hexdigest()[:10]


@dataclass
class AuditQuery:
    """Everything the /audit page can ask for. All fields optional."""

    action: str | None = None  # EXECUTED / REFUSED / ABSTAINED
    symbols: list[str] = field(default_factory=list)
    gate: str | None = None  # liquidity / earnings / term / stress / budget
    q: str | None = None  # free text across reason + rationale
    date_from: datetime | None = None
    date_to: datetime | None = None
    sort: str = "desc"  # newest first by default
    template: str | None = None  # template hash, for expanding one run


def parse_when(raw: str | None, *, end_of_day: bool = False) -> datetime | None:
    """ISO date or datetime. A bare date means midnight — or end of day for
    the range's upper bound, so 'to 2026-09-01' includes the 1st."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if end_of_day and len(raw) <= 10:  # date only
        parsed = datetime.combine(parsed.date(), time.max, tzinfo=UTC)
    return parsed


def failing_gates(row_detail: dict[str, Any] | None) -> list[str]:
    detail = row_detail or {}
    failed = detail.get("failed")
    if isinstance(failed, list):
        return [str(g) for g in failed]
    gates = detail.get("gates")
    if isinstance(gates, list):
        return [
            str(g.get("gate"))
            for g in gates
            if isinstance(g, dict) and not g.get("passed") and not g.get("skipped")
        ]
    return []


def load_rows(query: AuditQuery) -> list[DecisionRow]:
    """SQL narrows what it can; the text-shaped filters run in Python below.
    The whole log is ~2k rows — correctness and testability beat cleverness."""
    # CONFIG markers are era dividers, not decisions: they are loaded
    # separately (load_config_rows) and merged in regardless of the outcome
    # filter, so a filtered view still shows where the configuration changed.
    stmt = select(DecisionRow).where(DecisionRow.action != "CONFIG")
    if query.action:
        stmt = stmt.where(DecisionRow.action == query.action)
    if query.symbols:
        stmt = stmt.where(DecisionRow.symbol.in_([s.upper() for s in query.symbols]))
    if query.date_from:
        stmt = stmt.where(DecisionRow.ts >= query.date_from)
    if query.date_to:
        stmt = stmt.where(DecisionRow.ts <= query.date_to)
    order = DecisionRow.ts.asc() if query.sort == "asc" else DecisionRow.ts.desc()
    stmt = stmt.order_by(order, DecisionRow.id.asc())
    with session_scope() as session:
        rows = list(session.scalars(stmt).all())
        # Detach with attributes loaded — callers only read.
        for row in rows:
            session.expunge(row)
    return rows


def load_config_rows(query: AuditQuery) -> list[DecisionRow]:
    stmt = select(DecisionRow).where(DecisionRow.action == "CONFIG")
    if query.date_from:
        stmt = stmt.where(DecisionRow.ts >= query.date_from)
    if query.date_to:
        stmt = stmt.where(DecisionRow.ts <= query.date_to)
    with session_scope() as session:
        rows = list(session.scalars(stmt).all())
        for row in rows:
            session.expunge(row)
    return rows


def merge_by_time(
    rows: list[DecisionRow], config_rows: list[DecisionRow], sort: str
) -> list[DecisionRow]:
    reverse = sort != "asc"
    return sorted(
        rows + config_rows,
        key=lambda r: ((r.ts if r.ts.tzinfo else r.ts.replace(tzinfo=UTC)), r.id),
        reverse=reverse,
    )


def apply_text_filters(rows: list[DecisionRow], query: AuditQuery) -> list[DecisionRow]:
    out = rows
    if query.gate:
        out = [r for r in out if query.gate in failing_gates(r.detail)]
    if query.q:
        needle = query.q.lower()
        out = [
            r
            for r in out
            if needle in r.reason.lower() or needle in (r.model_rationale or "").lower()
        ]
    if query.template:
        out = [r for r in out if template_hash(r.reason) == query.template]
    return out


def _ts(row: DecisionRow) -> str:
    ts = row.ts if row.ts.tzinfo else row.ts.replace(tzinfo=UTC)
    return ts.isoformat()


def to_lite(row: DecisionRow) -> dict[str, Any]:
    """The table row: enough to scan, with the trace one click deeper."""
    detail = row.detail or {}
    return {
        "id": row.id,
        "ts": _ts(row),
        "action": row.action,
        "symbol": row.symbol,
        "kind": detail.get("kind"),
        "gates": failing_gates(detail),
        "reason": row.reason,
        "order_id": row.order_id,
        "risk_tier": row.risk_tier,
    }


def group_rows(rows: list[DecisionRow]) -> list[dict[str, Any]]:
    """Fill-bounded run grouping; see the module docstring for why not
    strictly consecutive. Rows arrive in display order; each run sits at the
    position of its first-seen member."""
    items: list[dict[str, Any]] = []
    open_runs: dict[str, dict[str, Any]] = {}

    for row in rows:
        if row.action == "CONFIG":
            # An era divider: the configuration changed here, so nothing
            # groups across it — reasoning on the two sides cites different
            # standing parameters.
            open_runs.clear()
            items.append({"type": "config", "id": row.id, "ts": _ts(row), "reason": row.reason})
            continue
        if row.action == "EXECUTED":
            open_runs.clear()  # a fill is a barrier: nothing groups across it
            items.append({"type": "decision", **to_lite(row)})
            continue
        key = f"{row.action}|{template_hash(row.reason)}"
        run = open_runs.get(key)
        if run is None:
            run = {
                "type": "run",
                "action": row.action,
                "template": template_hash(row.reason),
                "count": 0,
                "first_ts": _ts(row),
                "last_ts": _ts(row),
                "symbols": [],
                "kinds": [],
                "gates": failing_gates(row.detail),
                "sample": to_lite(row),
            }
            open_runs[key] = run
            items.append(run)
        run["count"] += 1
        # Display order may be desc or asc; keep the range honest either way.
        run["first_ts"] = min(run["first_ts"], _ts(row))
        run["last_ts"] = max(run["last_ts"], _ts(row))
        if row.symbol and row.symbol not in run["symbols"]:
            run["symbols"].append(row.symbol)
        kind = (row.detail or {}).get("kind")
        if kind and kind not in run["kinds"]:
            run["kinds"].append(kind)

    # A run of one is just a decision.
    return [
        {"type": "decision", **item["sample"]} if item["type"] == "run" and item["count"] == 1
        else item
        for item in items
    ]


def summarise(rows: list[DecisionRow]) -> dict[str, Any]:
    """The summary panel, computed from the current filter."""
    counts = {"EXECUTED": 0, "REFUSED": 0, "ABSTAINED": 0}
    by_gate: dict[str, int] = {}
    per_day: dict[str, int] = {}
    refused_symbols: dict[str, int] = {}

    for row in rows:
        counts[row.action] = counts.get(row.action, 0) + 1
        per_day[_ts(row)[:10]] = per_day.get(_ts(row)[:10], 0) + 1
        if row.action == "REFUSED":
            for gate in failing_gates(row.detail):
                by_gate[gate] = by_gate.get(gate, 0) + 1
            if row.symbol:
                refused_symbols[row.symbol] = refused_symbols.get(row.symbol, 0) + 1

    top_refused = max(refused_symbols.items(), key=lambda kv: kv[1]) if refused_symbols else None
    return {
        "count": len(rows),
        "executed": counts["EXECUTED"],
        "refused": counts["REFUSED"],
        "abstained": counts["ABSTAINED"],
        "by_gate": [
            {"gate": gate, "count": n}
            for gate, n in sorted(by_gate.items(), key=lambda kv: -kv[1])
        ],
        "per_day": [
            {"date": day, "count": n} for day, n in sorted(per_day.items())
        ],
        "top_refused": (
            {"symbol": top_refused[0], "count": top_refused[1]} if top_refused else None
        ),
    }


def run_query(
    query: AuditQuery, *, grouped: bool = True, offset: int = 0, limit: int = 100
) -> dict[str, Any]:
    rows = apply_text_filters(load_rows(query), query)
    summary = summarise(rows)
    # Era dividers join the stream after the summary is computed — they are
    # not decisions and never count. A template expansion is the one view
    # that excludes them: it renders inside a single run.
    merged = rows if query.template else merge_by_time(rows, load_config_rows(query), query.sort)
    items = (
        group_rows(merged)
        if grouped
        else [
            {"type": "config", "id": r.id, "ts": _ts(r), "reason": r.reason}
            if r.action == "CONFIG"
            else {"type": "decision", **to_lite(r)}
            for r in merged
        ]
    )
    total_items = len(items)
    page = items[offset : offset + limit]

    all_ts = [_ts(r) for r in rows]
    return {
        "summary": summary,
        "items": page,
        "total_items": total_items,
        "offset": offset,
        "limit": limit,
        "range": {"first": min(all_ts) if all_ts else None, "last": max(all_ts) if all_ts else None},
    }


def export_csv_rows(query: AuditQuery) -> list[list[str]]:
    """Header + one row per decision for the current filter, ungrouped."""
    rows = apply_text_filters(load_rows(query), query)
    if not query.action:  # the full record keeps its era markers
        rows = merge_by_time(rows, load_config_rows(query), query.sort)
    out = [["ts", "action", "symbol", "structure", "failing_gates", "reason",
            "model_rationale", "order_id", "risk_tier", "id"]]
    for r in rows:
        detail = r.detail or {}
        out.append([
            _ts(r),
            r.action,
            r.symbol or "",
            str(detail.get("kind") or ""),
            "|".join(failing_gates(detail)),
            r.reason,
            r.model_rationale or "",
            r.order_id or "",
            str(r.risk_tier),
            r.id,
        ])
    return out


def distinct_symbols() -> list[str]:
    with session_scope() as session:
        rows = session.execute(
            select(DecisionRow.symbol).where(DecisionRow.symbol.is_not(None)).distinct()
        ).all()
    return sorted({str(s) for (s,) in rows if s})
