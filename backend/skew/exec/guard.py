"""The two-instance guard.

Two copies of this desk pointed at the same account — a local dev instance and
the deployed one — would double-fill and corrupt each other's risk accounting.
The tell is simple: option positions open at the broker that THIS instance's
own book never created. At boot we compare the broker's open option positions
against every leg symbol our position store has ever recorded; anything foreign
means another writer owns this account, and this instance must stop opening
positions while continuing to watch its own.
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

# OCC option symbol: root + yymmdd + C/P + 8-digit strike.
_OCC = re.compile(r"^[A-Z.]{1,6}\d{6}[CP]\d{8}$")


def is_option_symbol(symbol: str, asset_class: str = "") -> bool:
    return asset_class == "us_option" or bool(_OCC.match(symbol))


def foreign_option_symbols(broker_positions: list[Any], our_leg_symbols: set[str]) -> list[str]:
    """Option positions at the broker that this instance's book never created.

    Pure comparison — testable with plain objects. ``broker_positions`` are the
    broker SDK's position records (only ``symbol`` and ``asset_class`` are
    read); ``our_leg_symbols`` is every leg symbol ever recorded in our
    position store, open or closed — a leg we closed but whose close never
    filled is still ours.
    """
    foreign = []
    for position in broker_positions:
        symbol = str(getattr(position, "symbol", "") or "")
        asset_class = str(getattr(position, "asset_class", "") or "")
        if not is_option_symbol(symbol, asset_class):
            continue  # equities in the account are not ours to reason about
        if symbol not in our_leg_symbols:
            foreign.append(symbol)
    return sorted(foreign)


def our_leg_symbols() -> set[str]:
    """Every option leg this instance's book has ever recorded."""
    from sqlalchemy import select

    from skew.audit.models import PositionRow
    from skew.db import session_scope

    symbols: set[str] = set()
    with session_scope() as session:
        for legs in session.scalars(select(PositionRow.legs)):
            symbols.update(str(s) for s in (legs or []))
    return symbols
