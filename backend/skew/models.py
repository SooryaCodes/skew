"""Cross-module data contracts.

Every shape that crosses a module boundary lives here, exactly as specified in
docs/06-DATA-CONTRACTS.md. The frontend types in frontend/lib/types.ts mirror
these one-for-one.

Two rules from the spec are enforced here rather than left to convention:

* ``Structure.max_loss`` is always populated and always positive. A structure
  without a computed max loss is a bug, not an edge case.
* ``Leg.ratio_qty`` across a structure must have a GCD of 1, or Alpaca rejects
  the order.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from math import gcd
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Regime = Literal["SELL_VOL", "BUY_VOL", "ABSTAIN"]
StructureKind = Literal["PUT_CREDIT", "CALL_CREDIT", "IRON_CONDOR", "CALL_DEBIT", "PUT_DEBIT"]
PositionIntent = Literal["BTO", "STO", "BTC", "STC"]
Side = Literal["BUY", "SELL"]
Right = Literal["CALL", "PUT"]
TimePoint = Literal["NOW", "MID", "EXPIRY"]
DecisionAction = Literal["EXECUTED", "REFUSED", "ABSTAINED"]

CONTRACT_MULTIPLIER = 100


def utcnow() -> datetime:
    return datetime.now(UTC)


class VolState(BaseModel):
    """The volatility picture for one underlying at one moment."""

    symbol: str
    spot: float
    iv_atm: float  # annualised, from Alpaca chain
    rv_20: float  # annualised, close-to-close
    rv_parkinson: float
    vrp: float  # iv_atm - rv_20 — the core signal
    rv_percentile: float  # today's RV within its 252d distribution
    term_slope: float  # positive = contango, negative = backwardation
    regime: Regime
    as_of: datetime = Field(default_factory=utcnow)

    # --- context the UI renders; not part of the core signal ---
    iv_rank_window_days: int = 0  # honest label: how much IV history we actually have
    iv_rank: float | None = None  # None until store.py has accumulated enough
    skew_curve: list[SkewPoint] = Field(default_factory=list)
    term_curve: list[TermPoint] = Field(default_factory=list)
    note: str = ""  # human-readable explanation when regime is ABSTAIN


class SkewPoint(BaseModel):
    """One point on the IV-vs-strike curve — the app's signature visual."""

    strike: float
    iv: float
    right: Right
    delta: float | None = None
    moneyness: float  # strike / spot


class TermPoint(BaseModel):
    """ATM IV at one expiration, for the term-structure slope."""

    expiry: date
    dte: int
    iv_atm: float


class Leg(BaseModel):
    """One option contract inside a structure."""

    symbol: str  # OCC contract symbol
    side: Side
    position_intent: PositionIntent
    ratio_qty: int = Field(ge=1)  # GCD across all legs must be 1
    strike: float
    expiry: date
    right: Right
    mid: float
    iv: float
    delta: float
    gamma: float
    theta: float
    vega: float

    # --- liquidity context, needed by the liquidity gate ---
    bid: float = 0.0
    ask: float = 0.0
    open_interest: int = 0
    volume: int = 0

    @property
    def signed_ratio(self) -> int:
        """+ratio for a long leg, -ratio for a short leg."""
        return self.ratio_qty if self.side == "BUY" else -self.ratio_qty

    @property
    def spread_pct(self) -> float:
        """Bid-ask spread as a fraction of mid. 1.0 when there is no usable quote."""
        if self.mid <= 0 or self.ask <= 0:
            return 1.0
        return (self.ask - self.bid) / self.mid


class Structure(BaseModel):
    """A fully specified, defined-risk options structure.

    ``max_loss`` is computed by the builder before construction and validated
    here. Nothing in the system may hold a Structure whose worst case is unknown.
    """

    model_config = ConfigDict(validate_assignment=True)

    id: str
    symbol: str
    kind: StructureKind
    legs: list[Leg]
    net_credit: float  # positive = credit received
    max_loss: float  # always positive, always computed
    max_profit: float
    breakevens: list[float]
    net_delta: float
    net_vega: float
    net_theta: float
    dte: int

    # --- context ---
    net_gamma: float = 0.0
    spot: float = 0.0
    qty: int = 1  # number of spreads
    created_at: datetime = Field(default_factory=utcnow)

    @field_validator("max_loss")
    @classmethod
    def _max_loss_positive(cls, v: float) -> float:
        if not (v > 0):
            raise ValueError(
                "max_loss must be positive and computed. A structure without a "
                "known worst case is a bug, not an edge case."
            )
        return v

    @model_validator(mode="after")
    def _validate_legs(self) -> Structure:
        if not 2 <= len(self.legs) <= 4:
            raise ValueError(
                f"Alpaca permits 2–4 legs for an mleg options order; got {len(self.legs)}."
            )
        ratios = [leg.ratio_qty for leg in self.legs]
        g = 0
        for r in ratios:
            g = gcd(g, r)
        if g != 1:
            raise ValueError(
                f"ratio_qty across legs must have GCD 1 or Alpaca rejects the order; "
                f"got {ratios} (gcd={g})."
            )
        expiries = {leg.expiry for leg in self.legs}
        if self.kind != "IRON_CONDOR" and len(expiries) > 2:
            raise ValueError("A vertical spread must not span more than two expiries.")
        return self

    @property
    def is_credit(self) -> bool:
        return self.net_credit > 0

    @property
    def limit_price(self) -> float:
        """Signed limit price for an mleg order.

        Alpaca convention: **positive is a debit, negative is a credit.** Getting
        this sign wrong inverts the trade, so it is derived in exactly one place.
        """
        return -round(self.net_credit, 2)

    @property
    def width(self) -> float:
        strikes = sorted({leg.strike for leg in self.legs})
        if len(strikes) < 2:
            return 0.0
        return max(strikes) - min(strikes)

    def describe(self) -> str:
        strikes = "/".join(f"{leg.strike:g}" for leg in self.legs)
        return f"{self.kind.replace('_', ' ').title()} {self.symbol} {strikes}"


class GateResult(BaseModel):
    """The outcome of one deterministic check.

    ``reason`` is user-facing copy, rendered verbatim in the UI. Write it with
    real numbers: "worst case -$1,240 at -2σ with IV +100%, exceeds tier budget
    $1,000".
    """

    gate: str
    passed: bool
    reason: str
    detail: dict[str, Any] = Field(default_factory=dict)
    # A gate is SKIPPED when it does not apply (e.g. term structure on a debit
    # spread). Skipped gates do not block; they render as "—" in the UI.
    skipped: bool = False


class StressCell(BaseModel):
    """One cell of the scenario grid."""

    price_shock: float  # in sigma
    iv_shock: float  # multiplier, e.g. 2.0 = +100%
    time_point: TimePoint
    pnl: float
    breached: bool


class Candidate(BaseModel):
    """A structure plus everything the system knows about whether it is safe."""

    structure: Structure
    gates: list[GateResult] = Field(default_factory=list)
    stress_grid: list[StressCell] = Field(default_factory=list)
    worst_case: float = 0.0
    passed_all: bool = False
    vol_state: VolState | None = None

    @property
    def id(self) -> str:
        return self.structure.id

    @property
    def failed_gates(self) -> list[GateResult]:
        return [g for g in self.gates if not g.passed and not g.skipped]

    def recompute_passed(self) -> bool:
        self.passed_all = bool(self.gates) and not self.failed_gates
        return self.passed_all


class Decision(BaseModel):
    """One append-only entry in the audit log. Never updated, never deleted."""

    id: str
    ts: datetime = Field(default_factory=utcnow)
    action: DecisionAction
    symbol: str | None = None
    structure_id: str | None = None
    reason: str
    model_rationale: str | None = None
    risk_tier: int
    order_id: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class RiskAuthority(BaseModel):
    """The earned risk tier. See docs/01-ARCHITECTURE.md §6."""

    tier: int
    max_loss_pct: float
    budget_dollars: float
    used_dollars: float
    closed_trades: int
    breaches: int
    drawdown_pct: float

    equity: float = 0.0
    open_positions: int = 0
    max_concurrent_positions: int = 3
    next_promotion: str = ""  # human copy: what it takes to size up

    @property
    def available_dollars(self) -> float:
        return max(0.0, self.budget_dollars - self.used_dollars)


class Position(BaseModel):
    """An open multi-leg position, reconstructed from Alpaca account positions."""

    id: str
    symbol: str
    kind: StructureKind | None = None
    legs: list[str] = Field(default_factory=list)
    qty: int = 1
    opened_at: datetime | None = None
    entry_credit: float = 0.0
    current_value: float = 0.0
    unrealized_pnl: float = 0.0
    max_loss: float = 0.0
    dte: int = 0
    exit_reason: str | None = None


class ModelSelection(BaseModel):
    """The bounded selector's response, after strict validation.

    ``candidate_id`` is either one of the IDs the model was given, or None for
    an abstention. Nothing else is representable.
    """

    candidate_id: str | None = None
    rationale: str = ""
    abstained: bool = True
    malformed: bool = False


class CycleReport(BaseModel):
    """What one pass of the loop did. Written to the audit log and served to the UI."""

    ts: datetime = Field(default_factory=utcnow)
    scanned: list[str] = Field(default_factory=list)
    vol_states: list[VolState] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# Resolve the forward reference from VolState -> SkewPoint.
VolState.model_rebuild()
