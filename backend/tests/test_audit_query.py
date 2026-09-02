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


# ------------------------------------------------------------------ config markers


def test_config_marker_is_a_divider_and_a_barrier():
    from skew.audit.query import merge_by_time

    cfg = row(3, "CONFIG", None, "Position limit raised from 3 to 6.")
    cfg.symbol = None
    decisions = [
        row(1, "REFUSED", "AAPL", CAPACITY),
        row(2, "REFUSED", "IWM", CAPACITY),
        row(4, "REFUSED", "MSFT", CAPACITY),
        row(5, "REFUSED", "NVDA", CAPACITY),
    ]
    merged = merge_by_time(decisions, [cfg], "asc")
    assert [r.id for r in merged] == ["d0001", "d0002", "d0003", "d0004", "d0005"]

    items = group_rows(merged)
    # run of 2 · divider · run of 2 — nothing groups across the era boundary
    assert [item["type"] for item in items] == ["run", "config", "run"]
    assert items[0]["count"] == 2 and items[2]["count"] == 2
    assert "Position limit" in items[1]["reason"]


def test_config_wording_for_the_watched_params():
    from skew.audit.log import _describe_change

    text = _describe_change("max_concurrent_positions", 3, 6)
    assert "raised from 3 to 6" in text
    assert "portfolio cap is unchanged" in text
    assert "prior limit" in text
    assert "45% to 25%" in _describe_change("profit_target_pct", 0.45, 0.25)
    assert "2x to 1x" in _describe_change("loss_limit_multiple", 2.0, 1.0)


def test_reconcile_entry_sign_and_max_loss_scaling():
    """A debit spread's true entry is NEGATIVE net_credit, and max loss moves
    with the actual fill: two AMD spreads at $5.00 debit are -$1,000 entry
    and $1,000 max loss, not the intended $406."""
    from skew.exec.reconcile import _true_entry
    from tests.test_gates import make_candidate

    structure = make_candidate().structure
    legs = {leg.symbol: (leg.signed_ratio * 2.0, 14.5 if leg.side == "BUY" else 9.5)
            for leg in structure.legs}
    entry = _true_entry(structure, legs, 2)
    # BUY leg 14.5, SELL leg 9.5 -> value +5.00/share -> net_credit -1000 for 2
    assert entry == -1000.0


def test_structural_max_loss_from_the_legs_alone():
    from skew.exec.reconcile import structural_max_loss
    from tests.test_gates import make_candidate

    structure = make_candidate().structure
    strikes = sorted({leg.strike for leg in structure.legs})
    width = (strikes[-1] - strikes[0]) * 100
    # A debit spread's max loss is the debit paid...
    if not structure.is_credit:
        assert structural_max_loss(structure, -500.0) == 500.0
    # ...and a credit spread's is width minus credit, whatever kind this is.
    assert structural_max_loss(structure, 80.0) == width - 80.0 or not structure.is_credit


def test_broker_supported_qty_reads_the_legs():
    from skew.exec.reconcile import broker_supported_qty
    from tests.test_gates import make_candidate

    structure = make_candidate().structure
    # Broker holds exactly one unit of every leg -> one spread supported.
    legs = {leg.symbol: (float(leg.signed_ratio), 5.0) for leg in structure.legs}
    assert broker_supported_qty(structure, legs) == 1
    # Double every leg -> two.
    legs2 = {k: (v[0] * 2, v[1]) for k, v in legs.items()}
    assert broker_supported_qty(structure, legs2) == 2
    # One leg missing -> zero; a partial structure is not this structure.
    legs3 = dict(list(legs.items())[1:])
    assert broker_supported_qty(structure, legs3) == 0


def test_committed_dollars_counts_resting_order_risk(tmp_path, monkeypatch):
    """An order working at the broker is promised risk: the budget gate must
    see it before the fill, or one cycle can submit its way past the
    portfolio cap (it did — four credit orders in eighty seconds)."""
    from skew.audit.models import OrderRow, PositionRow
    from skew.db import session_scope
    from skew.risk.authority import committed_dollars

    with session_scope() as session:
        session.add(PositionRow(
            id="T:OPEN:1", symbol="T", kind="PUT_CREDIT",
            qty=1, entry_credit=50.0, max_loss=200.0, is_open=True,
            legs=[], structure={},
        ))
        session.add(OrderRow(
            client_order_id="skew-resting-risk-test", symbol="T2",
            structure_id="T2:RESTING:1", kind="PUT_CREDIT", intent="OPEN",
            qty=1, limit_price=-0.5, net_credit=50.0, max_loss=300.0,
            status="new", legs=[], detail={},
        ))
        session.add(OrderRow(
            client_order_id="skew-dead-risk-test", symbol="T3",
            structure_id="T3:DEAD:1", kind="PUT_CREDIT", intent="OPEN",
            qty=1, limit_price=-0.5, net_credit=50.0, max_loss=999.0,
            status="expired", legs=[], detail={},
        ))
    try:
        committed, count = committed_dollars()
        assert committed >= 500.0  # 200 open + 300 resting
        assert count >= 2
        # the expired order's 999 must NOT be in there
        assert committed < 999.0 or committed - 500.0 < 499.0
    finally:
        with session_scope() as session:
            for model, key in ((PositionRow, "T:OPEN:1"), (OrderRow, "skew-resting-risk-test"), (OrderRow, "skew-dead-risk-test")):
                row = session.get(model, key)
                if row is not None:
                    session.delete(row)
