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
    """Net credit (negative = debit) of qty spreads at the broker's average
    entry prices. Falls back to the recorded entry when a leg is missing."""
    total = 0.0
    for leg in structure.legs:
        held = legs_at_broker.get(leg.symbol)
        price = held[1] if held else leg.mid
        total += leg.signed_ratio * price * CONTRACT_MULTIPLIER * qty
    return round(total, 2)


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

        # Filled: true quantity is the sum of FILLED orders, entry is the
        # broker's average — not what the book assumed at submission.
        true_qty = sum(int(o.qty or 0) for o in filled)
        structure = Structure.model_validate(row.structure) if row.structure else None
        if structure is None:
            report["warnings"].append(f"{row.id}: no structure JSON; cannot verify entry")
            continue
        true_entry = _true_entry(structure, legs_at_broker, true_qty)
        per_spread_max_loss = row.max_loss / row.qty if row.qty else row.max_loss

        if true_qty != row.qty or abs(true_entry - row.entry_credit) > 1.0:
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

    return report


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
