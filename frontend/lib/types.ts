/**
 * Mirrors backend/skew/models.py one-for-one.
 *
 * Kept hand-written rather than generated so the comments explaining what each
 * number means survive. If these drift from the Python side, the API contract
 * tests in backend/tests/test_api.py will notice before the UI does.
 */

export type Regime = "SELL_VOL" | "BUY_VOL" | "ABSTAIN";

export type StructureKind =
  | "PUT_CREDIT"
  | "CALL_CREDIT"
  | "IRON_CONDOR"
  | "CALL_DEBIT"
  | "PUT_DEBIT";

export type PositionIntent = "BTO" | "STO" | "BTC" | "STC";
export type Side = "BUY" | "SELL";
export type Right = "CALL" | "PUT";
export type TimePoint = "NOW" | "MID" | "EXPIRY";
export type DecisionAction = "EXECUTED" | "REFUSED" | "ABSTAINED";

/** One point on the IV-vs-strike curve — the app's signature visual. */
export interface SkewPoint {
  strike: number;
  iv: number;
  right: Right;
  delta: number | null;
  moneyness: number;
}

/** ATM IV at one expiration, for the term-structure slope. */
export interface TermPoint {
  expiry: string;
  dte: number;
  iv_atm: number;
}

/** The IV-vs-strike curve for one expiry. Front slice drawn, later ones ghosts. */
export interface SkewSlice {
  expiry: string;
  dte: number;
  points: SkewPoint[];
}

/** Realized-vol percentile band at one horizon, from the symbol's own history. */
export interface ConePoint {
  horizon: number;
  p10: number;
  p25: number;
  p50: number;
  p75: number;
  p90: number;
  current: number;
}

export interface VolState {
  symbol: string;
  spot: number;
  /** Annualised, straight from the Alpaca chain. Never inverted by us. */
  iv_atm: number;
  /** Annualised close-to-close, 20-day window, √252. */
  rv_20: number;
  rv_parkinson: number;
  /** iv_atm − rv_20. The core signal. Positive = vol is rich. */
  vrp: number;
  rv_percentile: number;
  /** Positive = contango (calm). Negative = backwardation (never sell into it). */
  term_slope: number;
  regime: Regime;
  as_of: string;
  /** How many days of IV history we actually have. Labelled honestly in the UI. */
  iv_rank_window_days: number;
  iv_rank: number | null;
  skew_curve: SkewPoint[];
  /** Front expiry first, then up to two later expiries as ghosts. */
  skew_slices: SkewSlice[];
  term_curve: TermPoint[];
  vol_cone: ConePoint[];
  note: string;
}

export interface Leg {
  symbol: string;
  side: Side;
  position_intent: PositionIntent;
  ratio_qty: number;
  strike: number;
  expiry: string;
  right: Right;
  mid: number;
  iv: number;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  bid: number;
  ask: number;
  open_interest: number;
  volume: number;
}

export interface Structure {
  id: string;
  symbol: string;
  kind: StructureKind;
  legs: Leg[];
  /** Positive = credit received. */
  net_credit: number;
  /** Always positive, always computed. A structure without one is a bug. */
  max_loss: number;
  max_profit: number;
  breakevens: number[];
  net_delta: number;
  net_vega: number;
  net_theta: number;
  dte: number;
  net_gamma: number;
  spot: number;
  qty: number;
  created_at: string;
  /** Derived server-side so the client never recomputes them independently. */
  is_credit: boolean;
  /** Alpaca mleg convention: positive is a debit, negative is a credit. */
  limit_price: number;
  /** For an iron condor this is the wing width, not the full strike span. */
  width: number;
}

export interface GateResult {
  gate: string;
  passed: boolean;
  /** User-facing copy. Rendered verbatim — never reworded on the client. */
  reason: string;
  detail: Record<string, unknown>;
  /** A gate that does not apply. Renders as "—" and does not block. */
  skipped: boolean;
}

export interface StressCell {
  price_shock: number;
  iv_shock: number;
  time_point: TimePoint;
  pnl: number;
  breached: boolean;
}

export interface Candidate {
  structure: Structure;
  gates: GateResult[];
  stress_grid: StressCell[];
  worst_case: number;
  passed_all: boolean;
  vol_state: VolState | null;
}

export interface Decision {
  id: string;
  ts: string;
  action: DecisionAction;
  symbol: string | null;
  structure_id: string | null;
  reason: string;
  model_rationale: string | null;
  risk_tier: number;
  order_id: string | null;
  detail: Record<string, unknown>;
}

export interface RiskAuthority {
  tier: number;
  max_loss_pct: number;
  budget_dollars: number;
  used_dollars: number;
  closed_trades: number;
  breaches: number;
  drawdown_pct: number;
  equity: number;
  open_positions: number;
  max_concurrent_positions: number;
  next_promotion: string;
  /** budget − used, floored at zero. Computed server-side. */
  available_dollars: number;
}

export interface Position {
  id: string;
  symbol: string;
  kind: StructureKind | null;
  legs: string[];
  qty: number;
  opened_at: string | null;
  entry_credit: number;
  current_value: number;
  unrealized_pnl: number;
  max_loss: number;
  dte: number;
  exit_reason: string | null;
}

export interface SystemStatus {
  ok: boolean;
  paper_only: true;
  base_url: string;
  kill_switch: boolean;
  market_open: boolean;
  broker_connected: boolean;
  model_connected: boolean;
  universe: string[];
  last_cycle: string | null;
  auto_execute: boolean;
  scheduler_running: boolean;
  /** Non-null when the bounded selector is unreachable — the desk cannot trade. */
  selector_error: string | null;
  /** The server's verdict: configured to trade AND the selector passed preflight. */
  armed: boolean;
  version: string;
}

export interface VrpHistoryRow {
  date: string;
  iv: number;
  rv: number | null;
}

export interface VrpHistory {
  symbol: string;
  /** Exactly how much IV history exists. Never implies more than it holds. */
  window_days: number;
  observations: number;
  series: VrpHistoryRow[];
  note: string;
}
