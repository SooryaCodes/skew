# 06 — Data Contracts

Define these first, in `skew/models.py`, before any logic. Every module consumes
and returns these shapes. The frontend types mirror them exactly.

## Python (Pydantic v2)

```python
class VolState(BaseModel):
    symbol: str
    spot: float
    iv_atm: float              # annualised, from Alpaca chain
    rv_20: float               # annualised, close-to-close
    rv_parkinson: float
    vrp: float                 # iv_atm - rv_20 — the core signal
    rv_percentile: float       # today's RV within its 252d distribution
    term_slope: float          # positive = contango, negative = backwardation
    regime: Literal["SELL_VOL", "BUY_VOL", "ABSTAIN"]
    as_of: datetime

class Leg(BaseModel):
    symbol: str                # OCC contract symbol
    side: Literal["BUY", "SELL"]
    position_intent: Literal["BTO", "STO", "BTC", "STC"]
    ratio_qty: int             # GCD across all legs must be 1
    strike: float
    expiry: date
    right: Literal["CALL", "PUT"]
    mid: float
    iv: float
    delta: float
    gamma: float
    theta: float
    vega: float

class Structure(BaseModel):
    id: str
    symbol: str
    kind: Literal["PUT_CREDIT", "CALL_CREDIT", "IRON_CONDOR",
                  "CALL_DEBIT", "PUT_DEBIT"]
    legs: list[Leg]
    net_credit: float          # positive = credit received
    max_loss: float            # always positive, always computed
    max_profit: float
    breakevens: list[float]
    net_delta: float
    net_vega: float
    net_theta: float
    dte: int

class GateResult(BaseModel):
    gate: str
    passed: bool
    reason: str                # human-readable; rendered verbatim in the UI
    detail: dict = {}          # e.g. failing stress cell coordinates

class StressCell(BaseModel):
    price_shock: float         # in sigma
    iv_shock: float            # multiplier, e.g. 2.0 = +100%
    time_point: Literal["NOW", "MID", "EXPIRY"]
    pnl: float
    breached: bool

class Candidate(BaseModel):
    structure: Structure
    gates: list[GateResult]
    stress_grid: list[StressCell]
    worst_case: float
    passed_all: bool

class Decision(BaseModel):
    id: str
    ts: datetime
    action: Literal["EXECUTED", "REFUSED", "ABSTAINED"]
    symbol: str | None
    structure_id: str | None
    reason: str
    model_rationale: str | None
    risk_tier: int
    order_id: str | None

class RiskAuthority(BaseModel):
    tier: int
    max_loss_pct: float
    budget_dollars: float
    used_dollars: float
    closed_trades: int
    breaches: int
    drawdown_pct: float
```

## TypeScript

Mirror these in `frontend/lib/types.ts`. Generate from the FastAPI OpenAPI schema
if you want them guaranteed in sync — `openapi-typescript` does it in one command
and removes a whole class of bug.

## Rules

- `max_loss` is **always** populated and **always** positive. A structure without a
  computed max loss is a bug, not an edge case. Assert it in the constructor.
- `reason` strings are user-facing copy. Write them properly in the backend, with
  numbers: `"worst case -$1,240 at -2σ with IV +100%, exceeds tier budget $1,000"`.
- Every `Decision` is append-only. Never update, never delete.
