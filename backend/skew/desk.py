"""The desk — one place that turns a symbol into gated candidates.

Sits between the data layer and the loop. ``evaluate_symbol`` does the whole
deterministic pipeline for one underlying:

    chain + bars -> VolState -> regime -> structures -> gate chain -> candidates

Everything above this in the stack (the loop, the API, the MCP server, the CLI)
calls into here, so there is exactly one implementation of "what does this desk
think about SPY right now" and no way for the MCP surface and the dashboard to
disagree about it.

The model appears nowhere in this file. By the time a candidate leaves here it
is fully specified and fully gated, and the only thing left to decide is which
of the survivors — if any — to take.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from skew.config import Settings
from skew.config import settings as default_settings
from skew.data.bars import BarClient
from skew.data.broker import Broker
from skew.data.calendar import EarningsCalendar, MarketCalendar
from skew.data.chains import ChainClient, OptionChain
from skew.data.store import distinct_history_days, history_window_days, iv_series
from skew.gates.base import GateContext, run_gates
from skew.models import Candidate, RiskAuthority, VolState
from skew.risk import authority
from skew.structures.credit import build_credit_candidates
from skew.structures.debit import build_debit_candidates
from skew.structures.selection import BudgetTooTight
from skew.vol.term import term_structure_slope
from skew.vol.vrp import build_vol_state

log = logging.getLogger(__name__)


@dataclass
class SymbolResult:
    """Everything the desk concluded about one symbol this cycle."""

    symbol: str
    vol_state: VolState | None = None
    # How many contracts the chain fetch returned — recorded so a decision
    # trace can show the scan step's real numbers, never recomputed ones.
    chain_contracts: int = 0
    candidates: list[Candidate] = field(default_factory=list)
    risk: RiskAuthority = field(
        default_factory=lambda: RiskAuthority(
            tier=0,
            max_loss_pct=0.005,
            budget_dollars=0.0,
            used_dollars=0.0,
            closed_trades=0,
            breaches=0,
            drawdown_pct=0.0,
        )
    )
    error: str | None = None

    @property
    def survivors(self) -> list[Candidate]:
        return [c for c in self.candidates if c.passed_all]

    @property
    def abstained(self) -> bool:
        return not self.survivors


class Desk:
    """The deterministic core. Construct once; reuse across cycles for caching."""

    def __init__(
        self,
        broker: Broker | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or default_settings
        self.broker = broker or Broker(self.settings)
        self.chains = ChainClient(self.broker)
        self.bars = BarClient(self.broker)
        self.earnings = EarningsCalendar()
        self.calendar = MarketCalendar(self.broker)
        self._equity: float | None = None

    # ------------------------------------------------------------------

    def start_cycle(self) -> None:
        """Drop per-cycle caches so a new pass sees fresh quotes."""
        self.chains.invalidate()
        self._equity = None

    def equity(self) -> float:
        """Account equity, cached for the cycle.

        Falls back to the configured expected equity when the account cannot be
        read, so the risk budget is never silently zero — a zero budget would
        make every candidate fail the budget gate for the wrong reason.
        """
        if self._equity is not None:
            return self._equity
        try:
            account = self.broker.get_account()
            self._equity = float(getattr(account, "equity", 0.0) or 0.0)
        except Exception as exc:  # noqa: BLE001 — logged, then falls back
            log.warning("could not read account equity: %s", exc)
            self._equity = self.settings.expected_equity
        if self._equity <= 0:
            self._equity = self.settings.expected_equity
        return self._equity

    def risk_authority(self) -> RiskAuthority:
        equity = self.equity()
        authority.record_equity(equity)
        used, open_count = authority.committed_dollars()
        return authority.get_authority(equity, used_dollars=used, open_positions=open_count)

    # ------------------------------------------------------------------

    def vol_state_for(self, symbol: str, chain: OptionChain | None = None) -> VolState:
        """The volatility picture for one symbol. Raises rather than returning zeros."""
        cfg = self.settings
        chain = chain or self.chains.get_chain(
            symbol, dte_min=cfg.target_dte_min, dte_max=cfg.target_dte_max + 60
        )
        series = self.bars.get_bars(symbol)
        return build_vol_state(
            chain,
            series,
            iv_history=iv_series(symbol),
            iv_history_window_days=history_window_days(symbol),
            iv_history_days=distinct_history_days(symbol),
            settings=cfg,
        )

    def evaluate_symbol(
        self,
        symbol: str,
        as_of: date | None = None,
        on_stage: Callable[[str], None] | None = None,
    ) -> SymbolResult:
        """The full deterministic pipeline for one underlying.

        Never raises: a symbol whose data is unusable produces a result carrying
        the reason, so the loop logs an abstention rather than dying.

        ``on_stage`` reports coarse progress — scanning, building, gating — so
        the operator's RUN CYCLE NOW control can show the desk thinking.
        """
        stage = on_stage or (lambda _s: None)
        cfg = self.settings
        symbol = symbol.upper()
        result = SymbolResult(symbol=symbol)

        try:
            result.risk = self.risk_authority()
        except Exception as exc:  # noqa: BLE001 — surfaced on the result
            result.error = f"risk authority unavailable: {exc}"
            return result

        try:
            stage("scanning")
            chain = self.chains.get_chain(
                symbol, dte_min=cfg.target_dte_min, dte_max=cfg.target_dte_max + 60
            )
            result.chain_contracts = len(chain.contracts)
            series = self.bars.get_bars(symbol)
            vol_state = build_vol_state(
                chain,
                series,
                iv_history=iv_series(symbol),
                iv_history_window_days=history_window_days(symbol),
                iv_history_days=distinct_history_days(symbol),
                settings=cfg,
            )
        except Exception as exc:  # noqa: BLE001 — abstain loudly, never guess
            result.error = str(exc)
            log.info("abstaining on %s: %s", symbol, exc)
            return result

        result.vol_state = vol_state
        ref = as_of or chain.as_of.date()

        if vol_state.regime == "ABSTAIN":
            result.error = vol_state.note
            return result

        stage("building")
        try:
            structures = self._build_structures(chain, vol_state, ref, result.risk)
        except BudgetTooTight as exc:
            # The builder worked backwards from the budget and even the
            # narrowest listed interval did not fit. Abstaining with the numbers
            # is the honest outcome — a candidate built anyway would only exist
            # to be refused.
            result.error = str(exc)
            log.info("abstaining on %s: %s", symbol, exc)
            return result
        if not structures:
            result.error = (
                f"No structure could be built from the {symbol} chain inside "
                f"{cfg.target_dte_min}–{cfg.target_dte_max} DTE that meets the liquidity floor."
            )
            return result

        context = GateContext(
            vol_state=vol_state,
            risk=result.risk,
            realized_vol=vol_state.rv_20,
            term=term_structure_slope(chain, as_of=ref),
            earnings=self.earnings,
            as_of=ref,
            min_open_interest=cfg.min_open_interest,
            max_spread_pct=cfg.max_spread_pct,
            min_volume=cfg.min_volume,
            earnings_blackout_days=cfg.earnings_blackout_days,
            earnings_unknown_blocks=cfg.earnings_unknown_blocks,
            risk_free_rate=cfg.risk_free_rate,
            routine_sigma=cfg.routine_sigma,
            routine_max_loss_pct=cfg.routine_max_loss_pct,
            max_breakeven_sigma=cfg.max_breakeven_sigma,
            open_positions=result.risk.open_positions,
            max_concurrent_positions=cfg.max_concurrent_positions,
        )

        stage("gating")
        for structure in structures:
            candidate = Candidate(structure=structure, vol_state=vol_state)
            result.candidates.append(run_gates(candidate, context))

        return result

    # ------------------------------------------------------------------

    def _build_structures(
        self, chain: OptionChain, vol_state: VolState, ref: date, risk: RiskAuthority
    ):
        """Structures appropriate to the regime, sized to the risk budget.

        SELL_VOL builds premium sales, BUY_VOL builds premium purchases. Nothing
        here consults a price forecast — the regime is a statement about whether
        volatility is expensive, and the structure follows from that alone.

        The builders work BACKWARDS from the budget: the binding cap is the
        smaller of the per-trade limit and the portfolio headroom left, so a
        structure is never built wider than the desk is permitted to take. The
        budget gate stays as the safety net; when it fires now it means a
        genuine constraint moved between build and gate, not builder noise.
        """
        cfg = self.settings
        budget = min(risk.budget_dollars, risk.available_dollars)
        common = {
            "qty": 1,
            "dte_min": cfg.target_dte_min,
            "dte_max": cfg.target_dte_max,
            "width_pct": cfg.target_width_pct,
            "min_open_interest": cfg.min_open_interest,
            "max_spread_pct": cfg.max_spread_pct,
            "as_of": ref,
            "budget": budget,
        }
        if vol_state.regime == "SELL_VOL":
            return build_credit_candidates(chain, short_delta=cfg.short_leg_delta_target, **common)
        if vol_state.regime == "BUY_VOL":
            return build_debit_candidates(chain, **common)
        return []

    # ------------------------------------------------------------------

    def scan(self, symbols: list[str] | None = None) -> list[SymbolResult]:
        """Evaluate the whole universe."""
        from skew.universe import effective_universe

        self.start_cycle()
        return [self.evaluate_symbol(s) for s in (symbols or effective_universe(self.settings))]

    def market_open(self) -> bool:
        return self.calendar.is_open(datetime.now(UTC))
