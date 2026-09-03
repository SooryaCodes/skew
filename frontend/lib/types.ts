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
// CONFIG marks a change to the desk's standing parameters — an era divider
// in the record, never counted or filtered as a trading decision.
export type DecisionAction =
  | "EXECUTED"
  | "REFUSED"
  | "ABSTAINED"
  | "CONFIG"
  | "CORRECTION";

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
  /** EXECUTED rows: true = broker confirmed the fill; false = submission
   *  died unfilled; null/undefined = resting or unknown. */
  order_filled?: boolean | null;
  reason: string;
  model_rationale: string | null;
  risk_tier: number;
  order_id: string | null;
  detail: Record<string, unknown>;
}

export interface RiskAuthority {
  tier: number;
  max_loss_pct: number;
  /** PER-TRADE cap: what any single position may risk. */
  budget_dollars: number;
  portfolio_pct: number;
  /** PORTFOLIO cap: what all open positions may risk together. */
  portfolio_cap_dollars: number;
  used_dollars: number;
  closed_trades: number;
  breaches: number;
  drawdown_pct: number;
  equity: number;
  open_positions: number;
  max_concurrent_positions: number;
  next_promotion: string;
  /** PORTFOLIO headroom: portfolio cap − committed, floored at zero. */
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

export interface ClosedPosition {
  id: string;
  symbol: string;
  kind: StructureKind | null;
  legs: string[];
  qty: number;
  opened_at: string | null;
  closed_at: string | null;
  entry_credit: number;
  max_loss: number;
  realized_pnl: number | null;
  exit_reason: string | null;
  days_held: number | null;
}

export interface ExitRules {
  profit_target_pct: number;
  loss_limit_multiple: number;
  exit_dte_threshold: number;
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
  /** Whether the desk has EVER published a volatility state. Separates
   *  "not armed" from "armed, first cycle pending" on an empty deployment. */
  has_published_state?: boolean;
  selector_configured?: boolean;
  universe_size?: number;
  last_cycle_at?: string | null;
  account_id_suffix?: string | null;
  account_error?: string | null;
  instance_conflict?: string | null;
  /** Entries halted by the drawdown circuit breaker; monitoring continues. */
  drawdown_paused?: boolean;
  /** Provenance, read from the broker at boot; null = unavailable, never a default. */
  equity?: number | null;
  starting_equity?: number | null;
  options_approval_level?: number | string | null;
  endpoint_is_paper?: boolean;
  exit_rules?: ExitRules;
  /** The most recent trading session — what the closed-market header names. */
  last_session: string;
  version: string;
}

export interface CycleProgress {
  running: boolean;
  phase: string;
  symbol: string | null;
  index: number;
  total: number;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export interface CycleStatus {
  progress: CycleProgress;
  last_cycle: {
    ts: string;
    scanned: number;
    candidates: number;
    decisions: number;
    errors: number;
  } | null;
}

export interface SessionSummary {
  session_date: string;
  market_open: boolean;
  /** The most recent single pass. Deliberately separate from the session
   * aggregates — mixing the two windows read as "0 survived · 1 filled". */
  cycle: {
    ts: string | null;
    scanned: number;
    candidates_built: number;
    survivors: number;
  };
  counts: Record<string, number>;
  counts_since: string;
  as_of: string | null;
  last_fill: {
    ts: string;
    symbol: string | null;
    reason: string;
    model_rationale: string | null;
    order_id: string | null;
  } | null;
}

export interface VrpHistoryRow {
  date: string;
  iv: number;
  rv: number | null;
}

export interface VrpHistory {
  /** Real observation span, for honest window labels. */
  first_ts?: string | null;
  last_ts?: string | null;
  distinct_days?: number;
  symbol: string;
  /** Exactly how much IV history exists. Never implies more than it holds. */
  window_days: number;
  observations: number;
  series: VrpHistoryRow[];
  note: string;
}

export interface RefusalExhibit {
  available: boolean;
  ts?: string;
  symbol?: string | null;
  kind?: string | null;
  structure_id?: string | null;
  max_loss?: number | null;
  reason?: string;
  cells?: StressCell[];
  note?: string;
}

export interface SurfaceSlice {
  dte: number;
  points: Array<{ strike: number; iv: number; moneyness: number }>;
}

export interface Surface {
  symbol: string;
  spot?: number;
  slices: SurfaceSlice[];
  error?: string;
}

// ---------------------------------------------------------------- /audit page

/** A table row on the full decision record — the trace holds the rest. */
export interface AuditLite {
  id: string;
  ts: string;
  action: DecisionAction;
  order_filled?: boolean | null;
  symbol: string | null;
  kind: string | null;
  gates: string[];
  reason: string;
  order_id: string | null;
  risk_tier: number;
}

/** A collapsed run: decisions sharing (outcome, reason template), bounded by
 *  fills. `sample` is the newest member, rendered as the run's face. */
export interface AuditRun {
  type: "run";
  action: DecisionAction;
  template: string;
  count: number;
  first_ts: string;
  last_ts: string;
  symbols: string[];
  kinds: string[];
  gates: string[];
  sample: AuditLite;
}

/** An era divider: the configuration changed at this timestamp. */
export interface AuditConfigMarker {
  type: "config";
  id: string;
  ts: string;
  reason: string;
}

export type AuditItem = ({ type: "decision" } & AuditLite) | AuditRun | AuditConfigMarker;

export interface AuditSummary {
  count: number;
  executed: number;
  refused: number;
  abstained: number;
  by_gate: Array<{ gate: string; count: number }>;
  per_day: Array<{ date: string; count: number }>;
  top_refused: { symbol: string; count: number } | null;
}

export interface AuditQueryResult {
  summary: AuditSummary;
  items: AuditItem[];
  total_items: number;
  offset: number;
  limit: number;
  range: { first: string | null; last: string | null };
  totals: Record<string, number>;
  account_suffix: string | null;
  symbols_seen: string[];
}

/** /api/strategy — every parameter the desk is running, read live. */
export interface StrategyConfig {
  signal: {
    vrp_sell_floor: number;
    vrp_buy_ceiling: number;
    term_far_target_dte: number;
    term_backwardation_floor: number;
    universe: string[];
  };
  construction: {
    short_leg_delta_target: number;
    target_dte_min: number;
    target_dte_max: number;
    target_width_pct: number;
    structures: string[];
  };
  gates: {
    order: string[];
    liquidity: { min_open_interest: number; max_spread_pct: number };
    earnings: { blackout_days: number; unknown_blocks: boolean };
    stress: { routine_sigma: number; routine_max_loss_pct: number };
    tallies: Record<string, { passed: number; refused: number }>;
  };
  model: { name: string };
  exits: {
    profit_target_pct: number;
    loss_limit_multiple: number;
    exit_dte_threshold: number;
    drawdown_breaker_pct: number;
  };
  tiers: Array<{
    level: number;
    max_loss_pct: number;
    portfolio_pct: number;
    trades_required: number;
    description: string;
  }>;
}
