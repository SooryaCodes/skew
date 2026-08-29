"""Closing orders — also atomic, also multi-leg.

A position that can be opened atomically but only closed leg by leg is not
defined risk; it is defined risk until the moment you need it not to be. So
closes go through the same ``mleg`` path as opens, with the position intents
inverted and the credit/debit sign flipped.

Closing a credit spread is a **debit** (we buy back what we sold), so the limit
price flips from negative to positive. That inversion is the mirror of the one
in ``submit.py`` and is derived here rather than passed in.
"""

from __future__ import annotations

import logging
from typing import Any

from skew.config import Settings
from skew.config import settings as default_settings
from skew.exec.submit import _persist_order, client_order_id
from skew.models import Leg, Structure

log = logging.getLogger(__name__)

CLOSING_INTENT: dict[str, str] = {"BTO": "STC", "STO": "BTC", "BTC": "STO", "STC": "BTO"}
OPPOSITE_SIDE: dict[str, str] = {"BUY": "SELL", "SELL": "BUY"}


def invert_leg(leg: Leg) -> Leg:
    """Flip one leg from opening to closing.

    A leg bought to open is sold to close, and vice versa. Prices are left as
    they were: the closing order is priced from a fresh quote by the caller, not
    from the entry mid.
    """
    return leg.model_copy(
        update={
            "side": OPPOSITE_SIDE[leg.side],
            "position_intent": CLOSING_INTENT[leg.position_intent],
        }
    )


def build_closing_structure(
    structure: Structure,
    current_mids: dict[str, float] | None = None,
) -> Structure:
    """Mirror a structure into the order that closes it.

    ``current_mids`` maps contract symbol to its current mid so the closing
    limit is priced off the live market. Without it the entry prices are reused,
    which is only acceptable for a dry run.
    """
    mids = current_mids or {}
    legs = []
    for leg in structure.legs:
        flipped = invert_leg(leg)
        if flipped.symbol in mids:
            flipped = flipped.model_copy(update={"mid": mids[flipped.symbol]})
        legs.append(flipped)

    from skew.structures.base import net_credit

    closing_credit = net_credit(legs, qty=structure.qty)

    # Max loss on a closing order is not a meaningful risk number — the position
    # already exists and this order reduces it. The model requires a positive
    # value, so the entry max loss is carried through as the honest bound on
    # what the close is unwinding.
    return structure.model_copy(
        update={
            "id": f"{structure.id}:CLOSE",
            "legs": legs,
            "net_credit": round(closing_credit, 2),
            "max_profit": abs(round(closing_credit, 2)) or structure.max_profit,
        }
    )


def close_structure(
    broker: Any,
    structure: Structure,
    current_mids: dict[str, float] | None = None,
    reason: str = "",
    use_limit: bool = True,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Submit the atomic multi-leg order that closes an open structure."""
    from datetime import UTC, datetime

    from skew.exec.submit import build_mleg_request

    cfg = settings or default_settings
    closing = build_closing_structure(structure, current_mids)
    client_id = client_order_id(closing)

    # Closing a credit spread is a debit and vice versa, so the limit sign
    # inverts. build_mleg_request asserts the convention on the closing
    # structure's own is_credit, which is already flipped.
    request = build_mleg_request(closing, client_id, use_limit=use_limit, settings=cfg)

    log.info(
        "closing %s as one mleg order (%s): limit %+.2f — %s",
        structure.id,
        client_id,
        closing.limit_price,
        reason or "no reason given",
    )

    order = broker.submit_order(request)
    record = {
        "client_order_id": client_id,
        "broker_order_id": str(getattr(order, "id", "") or ""),
        "status": str(getattr(order, "status", "") or "submitted"),
        "symbol": structure.symbol,
        "structure_id": structure.id,
        "kind": structure.kind,
        "qty": structure.qty,
        "limit_price": closing.limit_price,
        "net_credit": closing.net_credit,
        "max_loss": structure.max_loss,
        "legs": [
            {
                "symbol": leg.symbol,
                "side": leg.side,
                "position_intent": leg.position_intent,
                "ratio_qty": leg.ratio_qty,
            }
            for leg in closing.legs
        ],
        "submitted_at": datetime.now(UTC).isoformat(),
        "reason": reason,
    }
    _persist_order(record, intent="CLOSE")
    return record
