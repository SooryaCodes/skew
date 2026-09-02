"""The /audit query layer: templates, fill-bounded grouping, summaries.

All in-memory — DecisionRow objects are constructed directly, no session.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from skew.audit.models import DecisionRow
from skew.audit.query import (
    AuditQuery,
    apply_text_filters,
    group_rows,
    reason_template,
    summarise,
    template_hash,
)

T0 = datetime(2026, 9, 1, 14, 0, tzinfo=UTC)

CAPACITY = (
    "Already holding 3 of a maximum 3 concurrent positions. "
    "Capacity, not conviction, is the binding constraint here."
)
ALL_REFUSED = "All 3 candidates refused by the gate chain. No position taken."


def row(i: int, action: str, symbol: str, reason: str, detail: dict | None = None) -> DecisionRow:
    return DecisionRow(
        id=f"d{i:04d}",
        ts=T0 + timedelta(minutes=i),
        action=action,
        symbol=symbol,
        reason=reason,
        risk_tier=0,
        detail=detail or {},
    )


# ------------------------------------------------------------------ templates


def test_template_masks_particulars_but_not_meaning():
    a = reason_template("Max loss $310 fits the tier 0 budget for AAPL.")
    b = reason_template("Max loss $412 fits the tier 0 budget for MSFT.")
    c = reason_template("Stress breach: a 2-sigma move takes 84% of max loss.")
    assert a == b
    assert a != c


def test_capacity_refusals_share_one_template_across_symbols():
    assert template_hash(CAPACITY) == template_hash(CAPACITY.replace("3", "5"))


# ------------------------------------------------------------------ grouping


def test_interleaved_capacity_refusals_collapse_into_one_run():
    """The live pattern: each cycle interleaves refusals with abstentions.
    Strictly-consecutive grouping breaks every 2-3 rows; fill-bounded grouping
    folds the whole stretch."""
    rows = []
    i = 0
    for _cycle in range(3):
        for sym in ("AAPL", "IWM"):
            rows.append(row(i := i + 1, "REFUSED", sym, CAPACITY))
            rows.append(row(i := i + 1, "REFUSED", sym, CAPACITY))
            rows.append(row(i := i + 1, "ABSTAINED", sym, ALL_REFUSED))

    items = group_rows(rows)
    runs = [item for item in items if item["type"] == "run"]
    assert len(items) == 2  # one refusal run + one abstention run
    assert {r["action"] for r in runs} == {"REFUSED", "ABSTAINED"}
    refused = next(r for r in runs if r["action"] == "REFUSED")
    assert refused["count"] == 12
    assert set(refused["symbols"]) == {"AAPL", "IWM"}
    assert refused["first_ts"] < refused["last_ts"]


def test_fills_never_collapse_and_act_as_barriers():
    rows = [
        row(1, "REFUSED", "AAPL", CAPACITY),
        row(2, "REFUSED", "IWM", CAPACITY),
        row(3, "EXECUTED", "SPY", "Submitted iron condor for a credit of $59.50."),
        row(4, "REFUSED", "MSFT", CAPACITY),
        row(5, "REFUSED", "NVDA", CAPACITY),
    ]
    items = group_rows(rows)
    assert [item["type"] for item in items] == ["run", "decision", "run"]
    assert items[0]["count"] == 2 and items[2]["count"] == 2
    assert items[1]["action"] == "EXECUTED"


def test_a_genuinely_distinct_reason_renders_alone():
    rows = [
        row(1, "REFUSED", "AAPL", CAPACITY),
        row(2, "REFUSED", "AAPL", "Stress breach: a 2-sigma move takes 84% of max loss."),
        row(3, "REFUSED", "AAPL", CAPACITY),
    ]
    items = group_rows(rows)
    # capacity folds into one run of 2; the stress refusal stands alone
    assert len(items) == 2
    run = next(i for i in items if i["type"] == "run")
    single = next(i for i in items if i["type"] == "decision")
    assert run["count"] == 2
    assert "Stress" in single["reason"]


def test_a_run_of_one_is_just_a_decision():
    items = group_rows([row(1, "REFUSED", "AAPL", CAPACITY)])
    assert len(items) == 1 and items[0]["type"] == "decision"


# ------------------------------------------------------------------ filters


def test_gate_filter_reads_the_failed_list():
    rows = [
        row(1, "REFUSED", "AAPL", "x", {"failed": ["stress"]}),
        row(2, "REFUSED", "AAPL", "y", {"failed": ["budget"]}),
    ]
    out = apply_text_filters(rows, AuditQuery(gate="stress"))
    assert [r.id for r in out] == ["d0001"]


def test_free_text_search_is_case_insensitive():
    rows = [
        row(1, "REFUSED", "AAPL", "Capacity, not conviction."),
        row(2, "ABSTAINED", "TSLA", "VRP inside the band."),
    ]
    out = apply_text_filters(rows, AuditQuery(q="capacity"))
    assert [r.id for r in out] == ["d0001"]


def test_template_filter_expands_exactly_one_run():
    rows = [
        row(1, "REFUSED", "AAPL", CAPACITY),
        row(2, "REFUSED", "IWM", CAPACITY),
        row(3, "REFUSED", "AAPL", "Stress breach: 84% of max loss."),
    ]
    out = apply_text_filters(rows, AuditQuery(template=template_hash(CAPACITY)))
    assert [r.id for r in out] == ["d0001", "d0002"]


# ------------------------------------------------------------------ summary


def test_summary_counts_gates_days_and_top_refused():
    rows = [
        row(1, "REFUSED", "AAPL", "x", {"failed": ["stress"]}),
        row(2, "REFUSED", "AAPL", "y", {"failed": ["budget"]}),
        row(3, "REFUSED", "IWM", "z", {"failed": ["budget"]}),
        row(4, "EXECUTED", "SPY", "filled"),
        row(5, "ABSTAINED", "TSLA", "no edge"),
    ]
    s = summarise(rows)
    assert s["count"] == 5 and s["refused"] == 3 and s["executed"] == 1
    assert s["by_gate"][0] == {"gate": "budget", "count": 2}
    assert s["top_refused"] == {"symbol": "AAPL", "count": 2}
    assert s["per_day"][0]["count"] == 5
