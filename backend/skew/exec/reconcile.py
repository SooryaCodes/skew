"""Reconcile the book against the broker. The broker is the truth.

Positions used to be recorded at order SUBMISSION. On 2 September that
produced phantom positions: limit orders that expired unfilled stayed in the
book as open positions, one structure that filled twice was booked once, and
exit rules fired on positions the broker never held. This module is the
correction and the guarantee it cannot recur:

* Every cycle (and at boot), each open order's broker status is polled.
* A position is open only if the broker filled it. Expired or cancelled
  orders remove the phantom row — with a loud, dated, append-only CORRECTION
  entry in the audit log. History is never rewritten; corrections are new
  entries that say exactly what was wrong.
* Fill quantity and entry prices come from the broker, not from the order we
  wished we had.

Kept deliberately free of trading decisions: reconcile() observes and
corrects records. It never submits an order.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from skew.audit import log as audit
from skew.audit.models import OrderRow, PositionRow
from skew.db import session_scope
from skew.models import CONTRACT_MULTIPLIER, Structure

log = logging.getLogger(__name__)

# Broker order states that mean "this order is finished and did not fill".
DEAD_STATUSES = {"expired", "canceled", "cancelled", "rejected", "replaced", "done_for_day"}
FILLED = "filled"
# Still working at the broker; could fill later.
RESTING = {"new", "accepted", "pending_new", "accepted_for_bidding", "partially_filled", "held"}


def _order_status(broker: Any, client_id: str) -> str | None:
    try:
        order = broker.get_order_by_client_id(client_id)
    except Exception:  # noqa: BLE001 — an unknown order must not stop the pass
        log.warning("could not fetch order %s from broker", client_id)
        return None
    return str(getattr(order, "status", "") or "").lower().replace("orderstatus.", "")


def _broker_leg_entries(broker: Any) -> dict[str, tuple[float, float]]:
    """symbol -> (signed qty, avg entry price) for every option leg held."""
    out: dict[str, tuple[float, float]] = {}
    for p in broker.list_positions():
        try:
            out[str(p.symbol)] = (float(p.qty), float(p.avg_entry_price))
        except (TypeError, ValueError, AttributeError):
            continue
    return out


def _true_entry(structure: Structure, legs_at_broker: dict[str, tuple[float, float]], qty: int) -> float:
    """Net credit (positive = credit received, negative = debit paid) of qty
    spreads at the broker's average entry prices. The signed-ratio sum is the
    position's VALUE, so the credit convention is its negation — a debit
    spread has positive value and negative net_credit. Falls back to the
    recorded entry price when a leg is missing."""
    total = 0.0
    for leg in structure.legs:
        held = legs_at_broker.get(leg.symbol)
        price = held[1] if held else leg.mid
        total += leg.signed_ratio * price * CONTRACT_MULTIPLIER * qty
    return round(-total, 2)






def broker_supported_qty(
    structure: Structure, legs_at_broker: dict[str, tuple[float, float]]
) -> int:
    """How many units of this spread the broker's actual leg positions
    support. THE quantity authority: filled orders say what once happened,
    but legs say what is held now — a close or assignment that landed after
    our poll window shows up here first."""
    supported: int | None = None
    for leg in structure.legs:
        held = legs_at_broker.get(leg.symbol)
        held_qty = held[0] if held else 0.0
        need = leg.signed_ratio  # per unit of the spread
        units = int(held_qty // need) if need > 0 else int(held_qty // need) if need < 0 else 0
        # integer division with matching signs: floor(held/need) both negative
        # or both positive gives supported units; a sign mismatch gives <= 0.
        supported = units if supported is None else min(supported, units)
    return max(supported or 0, 0)


def structural_max_loss(structure: Structure, net_credit_per_spread: float) -> float:
    """Worst expiry P&L of one spread at the given entry, from the legs alone.

    Payoff is piecewise linear in spot, so probing zero, every strike, and a
    point beyond the highest strike covers every regime for the defined-risk
    verticals and condors this desk trades.
    """
    strikes = sorted({leg.strike for leg in structure.legs})
    probes = [0.0, *strikes, strikes[-1] * 2 + 100.0]
    worst = 0.0
    for spot in probes:
        value = sum(
            leg.signed_ratio
            * (max(spot - leg.strike, 0.0) if leg.right == "CALL" else max(leg.strike - spot, 0.0))
            for leg in structure.legs
        ) * CONTRACT_MULTIPLIER
        worst = min(worst, net_credit_per_spread + value)
    return round(-worst, 2)


def reconcile(broker: Any) -> dict[str, Any]:
    """One reconciliation pass. Returns a report of what was corrected."""
    report: dict[str, Any] = {"corrected": [], "verified": [], "warnings": []}
    if not getattr(broker, "available", False):
        report["warnings"].append("broker unavailable — reconciliation skipped")
        return report

    legs_at_broker = _broker_leg_entries(broker)

    with session_scope() as session:
        open_rows = list(
            session.scalars(select(PositionRow).where(PositionRow.is_open.is_(True))).all()
        )
        order_rows = list(session.scalars(select(OrderRow)).all())
        for row in open_rows + order_rows:
            session.expunge(row)

    orders_by_structure: dict[str, list[OrderRow]] = {}
    for order in order_rows:
        orders_by_structure.setdefault(order.structure_id, []).append(order)

    for row in open_rows:
        opens = [o for o in orders_by_structure.get(row.id, []) if o.intent == "OPEN"]
        statuses: dict[str, str] = {}
        for order in opens:
            status = _order_status(broker, order.client_order_id) or (order.status or "").lower()
            statuses[order.client_order_id] = status
            if status and status != (order.status or "").lower():
                with session_scope() as session:
                    stored = session.get(OrderRow, order.client_order_id)
                    if stored is not None:
                        stored.status = status

        filled = [o for o in opens if statuses.get(o.client_order_id) == FILLED]
        resting = [o for o in opens if statuses.get(o.client_order_id) in RESTING]

        if not filled and not resting:
            # Phantom: recorded at submission, never filled, orders all dead.
            named = ", ".join(
                f"{cid} ({statuses.get(cid, 'unknown')})" for cid in statuses
            ) or "no order record"
            with session_scope() as session:
                stored = session.get(PositionRow, row.id)
                if stored is not None:
                    session.delete(stored)
            audit.record_correction(
                f"Order expired unfilled — position record corrected. {row.id} was "
                f"recorded as an open position at order submission, but the broker "
                f"never filled it ({named}). The phantom position has been removed; "
                f"the original submission entry above stands as written.",
                symbol=row.symbol,
                detail={
                    "structure_id": row.id,
                    "orders": statuses,
                    "kind": "phantom_removed",
                },
            )
            report["corrected"].append({"structure_id": row.id, "action": "phantom_removed"})
            continue

        if not filled and resting:
            # Order still working: the position is not real yet. Remove the
            # premature row; a later fill is re-added by the orphan pass below.
            with session_scope() as session:
                stored = session.get(PositionRow, row.id)
                if stored is not None:
                    session.delete(stored)
            audit.record_correction(
                f"Position record corrected: {row.id} was recorded open at submission "
                f"but the order is still resting at the broker. The book now records "
                f"positions only when the broker reports a fill.",
                symbol=row.symbol,
                detail={"structure_id": row.id, "orders": statuses, "kind": "premature_removed"},
            )
            report["corrected"].append({"structure_id": row.id, "action": "premature_removed"})
            continue

        # Filled: the quantity truth is what the broker's LEGS support now —
        # filled orders say what once happened; legs say what is still held
        # (a close that filled after our poll window shows up here first).
        structure = Structure.model_validate(row.structure) if row.structure else None
        if structure is None:
            report["warnings"].append(f"{row.id}: no structure JSON; cannot verify entry")
            continue
        true_qty = broker_supported_qty(structure, legs_at_broker)
        if true_qty == 0:
            # Every leg gone: the position was closed away from the book
            # (late close fill, assignment, manual intervention). Record it
            # closed; realized P&L is marked unknown rather than invented.
            recovered = _recover_realized(broker, row)
            with session_scope() as session:
                stored = session.get(PositionRow, row.id)
                if stored is not None:
                    from datetime import UTC as _UTC
                    from datetime import datetime as _dt

                    stored.is_open = False
                    stored.closed_at = _dt.now(_UTC)
                    if recovered is not None:
                        stored.realized_pnl, stored.exit_reason = recovered
                    else:
                        stored.exit_reason = "reconciled_closed_at_broker"
            audit.record_correction(
                f"Position {row.id} is no longer held at the broker — its close "
                f"filled after the submission poll. "
                + (
                    f"Realized ${recovered[0]:+,.2f} on {recovered[1]}, taken from "
                    f"the closing order's actual fills."
                    if recovered is not None
                    else "No filled closing order could be found; realized P&L is "
                    "recorded as unavailable rather than invented."
                ),
                symbol=row.symbol,
                detail={"structure_id": row.id, "kind": "closed_at_broker",
                        "realized_pnl": recovered[0] if recovered else None,
                        "rule": recovered[1] if recovered else None},
            )
            report["corrected"].append({"structure_id": row.id, "action": "closed_at_broker"})
            continue
        true_entry = _true_entry(structure, legs_at_broker, true_qty)
        new_entry_per_spread = true_entry / true_qty if true_qty else true_entry
        # Max loss from first principles — expiry payoff over the strike grid
        # at the ACTUAL entry. No anchors on stored fields, so a previously
        # corrected (or previously wrong) row cannot compound an error.
        per_spread_max_loss = structural_max_loss(structure, new_entry_per_spread)
        expected_total_ml = round(per_spread_max_loss * true_qty, 2)

        if (
            true_qty != row.qty
            or abs(true_entry - row.entry_credit) > 1.0
            or abs(expected_total_ml - row.max_loss) > 1.0
        ):
            new_legs = []
            for leg in structure.legs:
                held = legs_at_broker.get(leg.symbol)
                new_legs.append(
                    leg.model_copy(update={"mid": held[1]}) if held else leg
                )
            corrected_structure = structure.model_copy(
                update={
                    "qty": true_qty,
                    "legs": new_legs,
                    "net_credit": true_entry,
                    "max_loss": round(per_spread_max_loss * true_qty, 2),
                }
            )
            with session_scope() as session:
                stored = session.get(PositionRow, row.id)
                if stored is not None:
                    stored.qty = true_qty
                    stored.entry_credit = true_entry
                    stored.max_loss = round(per_spread_max_loss * true_qty, 2)
                    stored.structure = corrected_structure.model_dump(mode="json")
            duplicate_note = (
                f" The structure was submitted {len(filled)} times and filled "
                f"{len(filled)} times — a duplicate the submission guard now refuses."
                if len(filled) > 1
                else ""
            )
            audit.record_correction(
                f"Position size corrected against the broker: {row.id} was booked as "
                f"{row.qty} spread(s) at ${row.entry_credit:,.2f}; the broker holds "
                f"{true_qty} at ${true_entry:,.2f} with max loss "
                f"${per_spread_max_loss * true_qty:,.2f}.{duplicate_note}",
                symbol=row.symbol,
                detail={
                    "structure_id": row.id,
                    "book_qty": row.qty,
                    "true_qty": true_qty,
                    "book_entry": row.entry_credit,
                    "true_entry": true_entry,
                    "filled_orders": [o.client_order_id for o in filled],
                    "kind": "size_corrected",
                },
            )
            report["corrected"].append(
                {"structure_id": row.id, "action": "size_corrected", "qty": true_qty}
            )
        else:
            report["verified"].append(row.id)

    # Orphan pass: OPEN orders with no position row (submissions recorded
    # since the fill-only rule). A late fill becomes a position; a dead order
    # gets its correction entry so the fills counter stays honest.
    open_ids = {row.id for row in open_rows}
    for structure_id, orders in orders_by_structure.items():
        if structure_id in open_ids:
            continue
        for order in orders:
            if order.intent != "OPEN":
                continue
            recorded = (order.status or "").lower()
            if recorded == FILLED or recorded in DEAD_STATUSES:
                continue  # already resolved on a previous pass
            status = _order_status(broker, order.client_order_id) or recorded
            if status == recorded:
                continue
            with session_scope() as session:
                stored = session.get(OrderRow, order.client_order_id)
                if stored is not None:
                    stored.status = status
            if status == FILLED:
                blob = (order.detail or {}).get("structure")
                if blob:
                    from skew.exec.monitor import record_open

                    structure = Structure.model_validate(blob)
                    record_open(structure, order.client_order_id)
                    audit.record_correction(
                        f"Late fill reconciled — {structure_id} filled at the broker "
                        f"after submission and is now recorded as an open position.",
                        symbol=order.symbol,
                        detail={"structure_id": structure_id, "kind": "late_fill_opened",
                                "order": order.client_order_id},
                    )
                    report["corrected"].append(
                        {"structure_id": structure_id, "action": "late_fill_opened"}
                    )
                else:
                    report["warnings"].append(
                        f"{order.client_order_id} filled but carries no structure JSON"
                    )
            elif status in DEAD_STATUSES:
                audit.record_correction(
                    f"Submission {order.client_order_id} for {structure_id} {status} "
                    f"unfilled — no position resulted. The submission entry above "
                    f"stands; it does not count as a fill.",
                    symbol=order.symbol,
                    detail={"structure_id": structure_id, "kind": "submission_died",
                            "order": order.client_order_id, "status": status},
                )
                report["corrected"].append(
                    {"structure_id": structure_id, "action": "submission_died"}
                )

    # CLOSE orders that died unfilled while the book already recorded the
    # close: the position is still open at the broker. Reopen it, loudly.
    with session_scope() as session:
        closed_rows = list(
            session.scalars(select(PositionRow).where(PositionRow.is_open.is_(False))).all()
        )
        for row in closed_rows:
            session.expunge(row)
    for row in closed_rows:
        closes = [o for o in orders_by_structure.get(row.id, []) if o.intent == "CLOSE"]
        if not closes:
            continue
        latest = closes[-1]
        status = _order_status(broker, latest.client_order_id) or (latest.status or "").lower()
        if status in DEAD_STATUSES:
            structure = Structure.model_validate(row.structure) if row.structure else None
            still_held = structure is not None and all(
                leg.symbol in legs_at_broker for leg in structure.legs
            )
            if still_held:
                with session_scope() as session:
                    stored = session.get(PositionRow, row.id)
                    if stored is not None:
                        stored.is_open = True
                        stored.closed_at = None
                        stored.realized_pnl = None
                        stored.exit_reason = None
                audit.record_correction(
                    f"Close order {latest.client_order_id} {status} unfilled — "
                    f"{row.id} is still open at the broker and the record has been "
                    f"reopened. Exit rules will re-evaluate it next cycle.",
                    symbol=row.symbol,
                    detail={"structure_id": row.id, "close_order": latest.client_order_id,
                            "kind": "close_unfilled_reopened"},
                )
                report["corrected"].append(
                    {"structure_id": row.id, "action": "close_unfilled_reopened"}
                )

    # Backfill: closed rows that never captured realized P&L (closed before
    # recovery existed). Recover from the broker's close fills; the correction
    # is written once, on success only — an unrecoverable row stays honest
    # ("unavailable") and is retried silently next pass.
    for row in closed_rows:
        if row.realized_pnl is not None or not row.closed_at:
            continue
        recovered = _recover_realized(broker, row)
        if recovered is None:
            continue
        realized, rule = recovered
        with session_scope() as session:
            stored = session.get(PositionRow, row.id)
            if stored is not None and stored.realized_pnl is None:
                stored.realized_pnl = realized
                stored.exit_reason = rule
        audit.record_correction(
            f"Realized P&L recovered from the broker's close fills: {row.id} "
            f"closed on {rule} for ${realized:+,.2f}. The close filled after the "
            f"submission poll and was reconciled without its fill price; the "
            f"figure above is the broker's, not an estimate.",
            symbol=row.symbol,
            detail={"structure_id": row.id, "kind": "realized_backfilled",
                    "realized_pnl": realized, "rule": rule},
        )
        report["corrected"].append({"structure_id": row.id, "action": "realized_backfilled"})

    return report


def _recover_realized(broker: Any, row: PositionRow) -> tuple[float, str] | None:
    """Realized P&L and the closing rule for a position whose close FILLED at
    the broker without being recorded (the fill landed after the submit poll).
    Recovered from the closing order's actual fill prices — never estimated.
    Returns None when no filled close order can be found."""
    with session_scope() as session:
        # Closing OrderRows persist under the ORIGINAL structure id (see
        # exit.py's record dict) with intent CLOSE — not under "<id>:CLOSE".
        closes = list(
            session.scalars(
                select(OrderRow).where(
                    OrderRow.structure_id == row.id, OrderRow.intent == "CLOSE"
                )
            ).all()
        )
        for order in closes:
            session.expunge(order)
    for order in reversed(closes):  # newest attempt first
        try:
            branch = broker.get_order_by_client_id(order.client_order_id)
        except Exception:  # noqa: BLE001 — recovery is best-effort, retried next pass
            continue
        status = str(getattr(branch, "status", "")).lower()
        if "filled" not in status or "partially" in status:
            continue
        prices = {
            str(leg.symbol): float(leg.filled_avg_price or 0.0)
            for leg in (getattr(branch, "legs", None) or [])
        }
        legs = order.legs or []
        if not legs or any(
            leg["symbol"] not in prices or prices[leg["symbol"]] <= 0 for leg in legs
        ):
            continue
        signed = sum((1 if leg["side"] == "BUY" else -1) * prices[leg["symbol"]] for leg in legs)
        close_credit = round(-signed * CONTRACT_MULTIPLIER * int(order.qty or row.qty or 1), 2)
        realized = round(row.entry_credit + close_credit, 2)
        rule = None
        with session_scope() as session:
            from skew.audit.models import DecisionRow

            dec = session.scalars(
                select(DecisionRow).where(DecisionRow.order_id == order.client_order_id)
            ).first()
            if dec is not None:
                rule = (dec.detail or {}).get("rule")
        return realized, (rule or "close")
    return None


def broker_holds_legs(broker: Any, structure: Structure, qty: int | None = None) -> bool:
    """True when the broker actually holds every leg of the structure, with the
    right sign and at least the closing quantity. The precondition for any
    close order — 28 rejected SPY closes fired on a phantom before this check
    existed."""
    want_qty = qty or structure.qty
    try:
        held = _broker_leg_entries(broker)
    except Exception:  # noqa: BLE001 — treat an unreadable broker as "cannot verify"
        return False
    for leg in structure.legs:
        have = held.get(leg.symbol)
        if have is None:
            return False
        have_qty = have[0]
        need = leg.signed_ratio * want_qty  # positive when long, negative when short
        if need > 0 and have_qty < need:
            return False
        if need < 0 and have_qty > need:
            return False
    return True
