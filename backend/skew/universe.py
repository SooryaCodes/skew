"""The effective trading universe.

The universe starts from the UNIVERSE env var and can be edited by the operator
at runtime — add or remove a symbol, persisted in SQLite, taking effect on the
next cycle. That is the entire scope of runtime configuration: risk tiers,
budgets and gate thresholds are deliberately not editable this way, because the
product's claim is that the desk decides autonomously inside deterministic
guardrails, and an editable limit is not an earned one.
"""

from __future__ import annotations

import re

from skew.audit.models import KVRow
from skew.config import Settings
from skew.config import settings as default_settings
from skew.db import session_scope

KEY = "universe"
MAX_SYMBOLS = 16
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z.]{0,5}$")


class UniverseError(ValueError):
    """Invalid universe edit. Carries a human-readable reason."""


def _stored() -> list[str] | None:
    with session_scope() as session:
        row = session.get(KVRow, KEY)
        if row is None:
            return None
        symbols = row.value.get("symbols")
        return list(symbols) if symbols else None


def effective_universe(settings: Settings | None = None) -> list[str]:
    """The stored override when one exists, the env-configured list otherwise."""
    cfg = settings or default_settings
    return _stored() or cfg.universe_symbols


def _store(symbols: list[str]) -> list[str]:
    with session_scope() as session:
        row = session.get(KVRow, KEY)
        if row is None:
            row = KVRow(key=KEY, value={})
            session.add(row)
        row.value = {"symbols": symbols}
    return symbols


def validate_symbol(symbol: str) -> str:
    cleaned = (symbol or "").strip().upper()
    if not _SYMBOL_RE.match(cleaned):
        raise UniverseError(
            f"{symbol!r} is not a plausible ticker — one to six letters, e.g. SPY or BRK.B."
        )
    return cleaned


def add_symbol(symbol: str, settings: Settings | None = None) -> list[str]:
    cleaned = validate_symbol(symbol)
    current = effective_universe(settings)
    if cleaned in current:
        return current
    if len(current) >= MAX_SYMBOLS:
        raise UniverseError(
            f"The universe is capped at {MAX_SYMBOLS} names — a five-minute loop "
            f"cannot honestly scan more. Remove one first."
        )
    return _store([*current, cleaned])


def remove_symbol(symbol: str, settings: Settings | None = None) -> list[str]:
    cleaned = validate_symbol(symbol)
    current = effective_universe(settings)
    if cleaned not in current:
        return current
    remaining = [s for s in current if s != cleaned]
    if not remaining:
        raise UniverseError("The universe cannot be emptied — the desk needs something to scan.")
    return _store(remaining)
