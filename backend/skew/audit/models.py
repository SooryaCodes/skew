"""SQLAlchemy tables.

Everything persistent lives here: the append-only decision log, the IV snapshot
history we have to accumulate ourselves (see docs/01-ARCHITECTURE.md §4), the
risk-tier state machine, and the order/position records.

The decision log is append-only by policy and by API — there is no update path
and no delete path anywhere in the codebase.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from skew.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DecisionRow(Base):
    """One entry in the audit trail. Append-only: never updated, never deleted.

    Refusals and abstentions are recorded exactly as prominently as executions —
    they are the best thing this system does.
    """

    __tablename__ = "decisions"

    # Which brokerage account this decision belongs to. Decision histories are
    # never mixed across accounts; boot refuses to write into another
    # account's log. Server-side only — the API never exposes the full id.
    account: Mapped[str] = mapped_column(String(24), default="", index=True)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    action: Mapped[str] = mapped_column(String(16), index=True)  # EXECUTED/REFUSED/ABSTAINED
    symbol: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    structure_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    model_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_tier: Mapped[int] = mapped_column(Integer, default=0)
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class IVSnapshotRow(Base):
    """ATM implied volatility, sampled every few minutes.

    Alpaca serves no historical IV — there is no endpoint, and any code claiming
    a 252-day IV rank from this API is lying. This table is option B from
    docs/01-ARCHITECTURE.md §4: build the history forward from the moment we
    start. The window length is surfaced honestly in the UI.
    """

    __tablename__ = "iv_snapshots"
    __table_args__ = (
        UniqueConstraint("symbol", "ts", name="uq_iv_symbol_ts"),
        Index("ix_iv_symbol_ts", "symbol", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    atm_iv: Mapped[float] = mapped_column(Float)
    spot: Mapped[float] = mapped_column(Float, default=0.0)
    dte: Mapped[int] = mapped_column(Integer, default=0)
    term_slope: Mapped[float] = mapped_column(Float, default=0.0)


class RiskStateRow(Base):
    """The earned risk tier. Exactly one row, id=1."""

    __tablename__ = "risk_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    tier: Mapped[int] = mapped_column(Integer, default=0)
    closed_trades: Mapped[int] = mapped_column(Integer, default=0)
    breaches: Mapped[int] = mapped_column(Integer, default=0)
    peak_equity: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    note: Mapped[str] = mapped_column(Text, default="")


class OrderRow(Base):
    """A submitted multi-leg order, keyed by our idempotent client_order_id."""

    __tablename__ = "orders"

    client_order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    structure_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(24))
    intent: Mapped[str] = mapped_column(String(8), default="OPEN")  # OPEN / CLOSE
    qty: Mapped[int] = mapped_column(Integer, default=1)
    limit_price: Mapped[float] = mapped_column(Float, default=0.0)
    net_credit: Mapped[float] = mapped_column(Float, default=0.0)
    max_loss: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(24), default="submitted")
    filled_avg_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    legs: Mapped[list] = mapped_column(JSON, default=list)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class PositionRow(Base):
    """An open structure we opened, so exits can be reasoned about as a unit.

    Alpaca reports positions leg by leg; the desk thinks in structures.
    """

    __tablename__ = "positions"

    account: Mapped[str] = mapped_column(String(24), default="")

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    entry_credit: Mapped[float] = mapped_column(Float, default=0.0)
    max_loss: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    exit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    legs: Mapped[list] = mapped_column(JSON, default=list)
    structure: Mapped[dict] = mapped_column(JSON, default=dict)


class KVRow(Base):
    """Small operator-set values that must survive a restart.

    Currently holds one key — the universe override. Not a general config
    store: risk tiers and budgets are deliberately NOT editable at runtime,
    because an editable limit is not an earned one.
    """

    __tablename__ = "kv"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


class EquityRow(Base):
    """Account equity samples, for the drawdown term in the risk authority."""

    __tablename__ = "equity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    equity: Mapped[float] = mapped_column(Float)
