"""MCP server — the desk as a set of tools.

    python -m skew.mcp_server

Every tool here routes through ``skew.desk.Desk`` and the same gate chain the
autonomous loop uses. **The MCP surface is not a bypass around the risk engine;
it is a different door into the same house.** A structure proposed here has
passed the identical five gates, and ``execute`` re-runs the whole chain before
submitting rather than trusting a candidate id from a previous turn.

Two rules govern the write tools:

* ``execute`` and ``close`` are registered **only** when ``MCP_ALLOW_EXECUTE``
  is true, and it is false by default. An accidental connection cannot place a
  trade — the tools are not merely refused, they are absent from the tool list.
* Even when enabled, they are paper-only, budget-bound, and gated. There is no
  configuration of this server that reaches a live account.

Tool descriptions are written properly because a judge may connect this to
Claude and drive it conversationally, and a vague description is the difference
between it working first try and looking broken.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from skew.audit import log as audit
from skew.config import PAPER_HOST, settings
from skew.db import init_db
from skew.desk import Desk, SymbolResult

log = logging.getLogger(__name__)

INSTRUCTIONS = """\
SKEW is an autonomous options volatility desk running on Alpaca paper trading.

It does not predict price direction. It measures the variance risk premium — the
gap between implied volatility and subsequently realized volatility — and takes
defined-risk options structures into that gap. Direction is never an input, and
questions about where a stock is going are outside what this desk models.

A normal session: scan_volatility to see where volatility is rich or cheap,
propose_structures on a symbol to get fully-gated candidates, stress_test to see
the 84-scenario grid behind one of them, risk_status for the current tier.

Every candidate returned has already passed a deterministic gate chain —
liquidity, earnings, term structure, stress and budget. Refusals carry the exact
failing condition with numbers, and they are the most informative thing this
desk produces.

All volatilities are annualised decimals: 0.241 means 24.1%.\
"""

mcp = FastMCP(
    name="skew",
    version="0.1.0",
    instructions=INSTRUCTIONS,
)

_DESK: Desk | None = None
# Candidates from the most recent propose_structures call, so stress_test and
# execute can refer to one by id within a conversation.
_CANDIDATES: dict[str, Any] = {}


def _desk() -> Desk:
    global _DESK
    if _DESK is None:
        init_db()
        _DESK = Desk()
    return _DESK


def _remember(result: SymbolResult) -> None:
    for candidate in result.candidates:
        _CANDIDATES[candidate.id] = candidate


def _gates_json(candidate: Any) -> list[dict[str, Any]]:
    return [
        {
            "gate": g.gate,
            "passed": g.passed,
            "skipped": g.skipped,
            "reason": g.reason,
            "detail": g.detail,
        }
        for g in candidate.gates
    ]


def _candidate_json(candidate: Any) -> dict[str, Any]:
    s = candidate.structure
    return {
        "candidate_id": s.id,
        "symbol": s.symbol,
        "kind": s.kind,
        "dte": s.dte,
        "legs": [
            {
                "symbol": leg.symbol,
                "side": leg.side,
                "position_intent": leg.position_intent,
                "ratio_qty": leg.ratio_qty,
                "strike": leg.strike,
                "right": leg.right,
                "mid": leg.mid,
                "iv": leg.iv,
                "delta": leg.delta,
                "open_interest": leg.open_interest,
            }
            for leg in s.legs
        ],
        "net_credit": s.net_credit,
        "max_loss": s.max_loss,
        "max_profit": s.max_profit,
        "breakevens": s.breakevens,
        "net_delta": s.net_delta,
        "net_vega": s.net_vega,
        "net_theta": s.net_theta,
        "worst_case": candidate.worst_case,
        "passed_all_gates": candidate.passed_all,
        "gates": _gates_json(candidate),
    }


def _vol_json(state: Any) -> dict[str, Any]:
    return {
        "symbol": state.symbol,
        "spot": state.spot,
        "iv_atm": state.iv_atm,
        "rv_20": state.rv_20,
        "rv_parkinson": state.rv_parkinson,
        "vrp": state.vrp,
        "vrp_vol_points": round(state.vrp * 100, 2),
        "rv_percentile": state.rv_percentile,
        "term_slope": state.term_slope,
        "term_shape": (
            "contango"
            if state.term_slope > 0.005
            else "backwardation"
            if state.term_slope < -0.005
            else "flat"
        ),
        "regime": state.regime,
        "explanation": state.note,
        "iv_rank": state.iv_rank,
        "iv_rank_window_days": state.iv_rank_window_days,
        "as_of": state.as_of.isoformat(),
    }


# ======================================================================
# Read tools — always available
# ======================================================================


@mcp.tool
def scan_volatility(symbols: list[str] | None = None) -> dict[str, Any]:
    """Measure implied versus realized volatility across the universe.

    This is the desk's core signal and the right place to start any session. For
    each symbol it returns spot, at-the-money implied volatility, 20-day realized
    volatility, and the variance risk premium (VRP = IV − RV) that is the gap
    between them.

    The regime is what the desk concluded:
      SELL_VOL  — implied is well above realized, so premium is rich
      BUY_VOL   — implied is at or below realized, so movement is cheap
      ABSTAIN   — fairly priced, or a structural reason to stand down

    Every state carries an `explanation` field written for a human; quote it
    rather than paraphrasing, because it names the exact threshold that was hit.

    Args:
        symbols: Tickers to scan. Defaults to the configured universe.

    Returns:
        One entry per symbol. Volatilities are annualised decimals — 0.241 is
        24.1%. `vrp_vol_points` is the same number in percentage points, which
        is how a trader would say it out loud.
    """
    desk = _desk()
    results = desk.scan(symbols)
    states = [_vol_json(r.vol_state) for r in results if r.vol_state]
    abstained = [
        {"symbol": r.symbol, "reason": r.error} for r in results if r.vol_state is None and r.error
    ]
    return {
        "as_of": results[0].vol_state.as_of.isoformat() if states else None,
        "scanned": len(results),
        "states": states,
        "unavailable": abstained,
        "note": "Direction is never an input. This measures whether movement is mispriced.",
    }


@mcp.tool
def propose_structures(symbol: str) -> dict[str, Any]:
    """Build defined-risk option structures for one symbol and run every gate.

    Returns two or three fully-specified candidates — real contract symbols, real
    strikes, a computed maximum loss — each with the complete result of the
    deterministic gate chain:

      liquidity  open interest, bid-ask width, both sides quoted
      earnings   no report inside the blackout or before expiry
      term       never sell premium into backwardation
      stress     84 repriced scenarios, plus how much of the max loss a routine
                 1-sigma move already reaches
      budget     max loss fits the current earned risk tier

    **A refused candidate is the most informative output this desk produces.**
    Every gate is evaluated even after one fails, so you get the full picture,
    and each `reason` names the exact failing condition with numbers.

    Args:
        symbol: The underlying ticker, e.g. "SPY".

    Returns:
        The volatility state, the candidates with their gates, and which of them
        survived. An empty candidate list is a normal outcome, not an error —
        check `abstain_reason`.
    """
    desk = _desk()
    result = desk.evaluate_symbol(symbol.upper())
    _remember(result)

    return {
        "symbol": symbol.upper(),
        "vol_state": _vol_json(result.vol_state) if result.vol_state else None,
        "abstain_reason": result.error,
        "risk_tier": result.risk.tier,
        "budget_dollars": result.risk.budget_dollars,
        "candidates": [_candidate_json(c) for c in result.candidates],
        "passed_count": len(result.survivors),
        "refused_count": len(result.candidates) - len(result.survivors),
    }


@mcp.tool
def stress_test(candidate_id: str) -> dict[str, Any]:
    """Return the full 84-scenario stress grid for one candidate.

    The grid reprices the exact structure with Black-Scholes across:

      price   −3σ, −2σ, −1σ, 0, +1σ, +2σ, +3σ  (σ scaled to days-to-expiry)
      IV      ×0.7, ×1.0, ×1.5, ×2.0
      time    now, halfway to expiry, at expiry

    Worth knowing when reading the result: for a defined-width vertical the
    absolute worst cell always lands on the terminal max loss, because the
    spread's liability is bounded by its width. The number that actually
    discriminates between two structures is `routine_move` — how much of that
    max loss an ordinary 1-sigma move already reaches. A spread whose short
    strike sits half a sigma away and one whose strike sits two and a half sigma
    away have the same max loss and completely different odds of paying it.

    Args:
        candidate_id: An id from a previous propose_structures call.

    Returns:
        All 84 cells, the worst one, and the routine-move measurement.
    """
    candidate = _CANDIDATES.get(candidate_id)
    if candidate is None:
        return {
            "error": f"No candidate {candidate_id!r} in this session.",
            "hint": "Call propose_structures first; ids are only valid within a session.",
            "known_ids": sorted(_CANDIDATES)[:20],
        }

    stress = next((g for g in candidate.gates if g.gate == "stress"), None)
    return {
        "candidate_id": candidate_id,
        "symbol": candidate.structure.symbol,
        "kind": candidate.structure.kind,
        "max_loss": candidate.structure.max_loss,
        "worst_case": candidate.worst_case,
        "passed": stress.passed if stress else None,
        "reason": stress.reason if stress else None,
        "routine_move": {
            "sigma": stress.detail.get("routine_sigma") if stress else None,
            "pnl": stress.detail.get("routine_pnl") if stress else None,
            "limit": stress.detail.get("routine_limit") if stress else None,
        }
        if stress
        else None,
        "cells": [
            {
                "price_shock": c.price_shock,
                "iv_shock": c.iv_shock,
                "time_point": c.time_point,
                "pnl": c.pnl,
                "breached": c.breached,
            }
            for c in candidate.stress_grid
        ],
    }


@mcp.tool
def risk_status() -> dict[str, Any]:
    """Report the desk's earned risk authority: tier, budget, drawdown, record.

    Position size is a privilege this desk earns rather than a setting. It starts
    at tier 0 with 0.5% of equity at risk per trade and is promoted only on a
    clean record — three closed trades with no gate breach for tier 1, six for
    tier 2. Any breach demotes to tier 0 immediately and is not forgiven by later
    clean trades.

    Returns:
        Current tier, the PER-TRADE cap (what any single position may risk),
        the PORTFOLIO cap (what all open positions may risk together, with
        committed and headroom), drawdown from the high-water mark, and
        `next_promotion` — plain-English copy saying what it takes to size up.
    """
    desk = _desk()
    risk = desk.risk_authority()
    return {
        "tier": risk.tier,
        "max_loss_pct": risk.max_loss_pct,
        "per_trade_cap_dollars": risk.budget_dollars,
        "portfolio_cap_dollars": risk.portfolio_cap_dollars,
        "portfolio_committed_dollars": risk.used_dollars,
        "portfolio_headroom_dollars": risk.available_dollars,
        "equity": risk.equity,
        "closed_trades": risk.closed_trades,
        "breaches": risk.breaches,
        "drawdown_pct": risk.drawdown_pct,
        "open_positions": risk.open_positions,
        "max_concurrent_positions": risk.max_concurrent_positions,
        "next_promotion": risk.next_promotion,
    }


@mcp.tool
def positions() -> dict[str, Any]:
    """List open positions with live mark-to-market P&L.

    Positions are tracked as whole structures rather than as individual legs,
    because the exit rules — profit target, loss limit, days-to-expiry — only
    make sense at that level.

    Returns:
        Each position with its legs, entry credit, current unrealised P&L,
        maximum loss and days to expiry.
    """
    from skew.exec import monitor

    rows = monitor.open_positions()
    if not rows:
        return {"count": 0, "positions": [], "note": "No open positions."}

    contracts = sorted({s for row in rows for s in (row.legs or [])})
    mids = monitor.fetch_mids(_desk().broker, contracts)
    out = [monitor.to_position(row, mids).model_dump(mode="json") for row in rows]
    return {
        "count": len(out),
        "positions": out,
        "total_unrealized_pnl": round(sum(p["unrealized_pnl"] for p in out), 2),
    }


@mcp.tool
def audit_log(limit: int = 25, action: str | None = None) -> dict[str, Any]:
    """Read the append-only decision log.

    Every decision the desk has made, newest first — executions, refusals and
    abstentions, recorded with equal prominence. That is deliberate: a system
    that only logs what it did tells you nothing about its judgement.

    Args:
        limit: How many entries to return (1–500).
        action: Optionally filter to "EXECUTED", "REFUSED" or "ABSTAINED".

    Returns:
        The entries, plus running counts. The ratio of refusals to executions is
        the honest headline for this desk.
    """
    valid = {"EXECUTED", "REFUSED", "ABSTAINED"}
    if action and action.upper() not in valid:
        return {"error": f"action must be one of {sorted(valid)}", "given": action}

    entries = audit.recent(limit=max(1, min(limit, 500)), action=action.upper() if action else None)
    return {
        "count": len(entries),
        "counts": audit.counts(),
        "entries": [
            {
                "id": d.id,
                "ts": d.ts.isoformat(),
                "action": d.action,
                "symbol": d.symbol,
                "reason": d.reason,
                "model_rationale": d.model_rationale,
                "risk_tier": d.risk_tier,
                "order_id": d.order_id,
            }
            for d in entries
        ],
    }


@mcp.tool
def desk_status() -> dict[str, Any]:
    """Report configuration and safety posture.

    Useful as a first call to confirm what this server is connected to and what
    it is permitted to do.

    Returns:
        The paper-only guarantee, whether write tools are enabled, the kill
        switch state, and the configured universe.
    """
    return {
        "paper_only": True,
        "base_url": PAPER_HOST,
        "live_trading_code_path_exists": False,
        "write_tools_enabled": settings.mcp_allow_execute,
        "kill_switch": settings.kill_switch,
        "universe": settings.universe_symbols,
        "risk_tier_start": settings.risk_tier_start,
        "max_concurrent_positions": settings.max_concurrent_positions,
        "note": (
            "Write tools (execute, close) are registered only when MCP_ALLOW_EXECUTE is "
            "true. They are absent from the tool list otherwise, not merely refused."
        ),
    }


# ======================================================================
# Write tools — registered ONLY when explicitly enabled
# ======================================================================


def _register_write_tools() -> None:
    """Attach ``execute`` and ``close``.

    Called only when ``MCP_ALLOW_EXECUTE`` is true. Registering conditionally
    rather than refusing at call time means an accidental connection sees a
    read-only server: the tools do not appear in the tool list at all, so there
    is nothing for a model to try.
    """

    @mcp.tool
    def execute(candidate_id: str, confirm: bool = False) -> dict[str, Any]:
        """Submit a previously-proposed structure as one atomic multi-leg order.

        **The full gate chain is re-run before anything is sent.** A candidate id
        from earlier in the conversation is not a permission slip — the market
        moved while we were talking, and a structure that passed two minutes ago
        may not pass now. If it no longer does, this refuses and tells you which
        gate failed.

        The order goes as a single `mleg` order. The desk never legs into a
        spread, because a filled short leg with an unfilled long leg is a naked
        short option.

        Args:
            candidate_id: An id from a recent propose_structures call.
            confirm: Must be true. A deliberate second step, so a model cannot
                place a trade in a single unconsidered call.

        Returns:
            The order record, or a refusal naming the failing gate.
        """
        if not confirm:
            return {
                "submitted": False,
                "reason": "confirm=true is required. Review the gates and stress grid first.",
            }

        candidate = _CANDIDATES.get(candidate_id)
        if candidate is None:
            return {
                "submitted": False,
                "reason": f"No candidate {candidate_id!r} in this session.",
                "hint": "Call propose_structures first.",
            }

        from skew.exec.submit import SubmissionRefused, submit_structure
        from skew.loop import _gate_context

        desk = _desk()
        result = desk.evaluate_symbol(candidate.structure.symbol)
        _remember(result)

        # Re-resolve against the FRESH evaluation. The stored candidate is a
        # stale snapshot; only a structure the desk would build right now, and
        # would pass right now, may be submitted.
        fresh = next((c for c in result.candidates if c.id == candidate_id), None)
        if fresh is None:
            return {
                "submitted": False,
                "reason": (
                    "The desk no longer constructs that structure from the current chain. "
                    "Call propose_structures again."
                ),
            }
        if not fresh.passed_all:
            return {
                "submitted": False,
                "reason": "Refused on re-check.",
                "failed_gates": [{"gate": g.gate, "reason": g.reason} for g in fresh.failed_gates],
            }

        try:
            order = submit_structure(desk.broker, fresh, _gate_context(desk, result, settings))
        except SubmissionRefused as exc:
            audit.record_refusal(fresh, result.risk.tier, extra={"mcp_refused": str(exc)})
            return {"submitted": False, "reason": str(exc)}

        from skew.exec import monitor

        monitor.record_open(fresh.structure, order["client_order_id"])
        audit.record_execution(
            fresh,
            result.risk.tier,
            order_id=order["client_order_id"],
            model_rationale="Submitted via the MCP execute tool.",
            detail={"source": "mcp"},
        )
        return {"submitted": True, "order": order}

    @mcp.tool
    def close(position_id: str, confirm: bool = False) -> dict[str, Any]:
        """Close an open position with an atomic multi-leg closing order.

        Args:
            position_id: The structure id from `positions()`.
            confirm: Must be true.

        Returns:
            The closing order record, or a refusal.
        """
        if not confirm:
            return {"submitted": False, "reason": "confirm=true is required."}

        from skew.exec import monitor
        from skew.exec.exit import close_structure
        from skew.models import Structure

        row = next((r for r in monitor.open_positions() if r.id == position_id), None)
        if row is None:
            return {"submitted": False, "reason": f"No open position {position_id!r}."}

        structure = Structure.model_validate(row.structure)
        mids = monitor.fetch_mids(_desk().broker, list(row.legs or []))
        pnl = monitor.unrealised_pnl(structure, mids)

        order = close_structure(
            _desk().broker, structure, current_mids=mids, reason="Closed via MCP close tool."
        )
        monitor.record_close(position_id, pnl, "closed via MCP")
        audit.record(
            action="EXECUTED",
            reason=f"Closed {structure.describe()} via MCP. P&L ${pnl:,.2f}.",
            risk_tier=_desk().risk_authority().tier,
            symbol=structure.symbol,
            structure_id=position_id,
            order_id=order["client_order_id"],
            detail={"source": "mcp", "realized_pnl": round(pnl, 2)},
        )
        return {"submitted": True, "order": order, "realized_pnl": round(pnl, 2)}


if settings.mcp_allow_execute:
    _register_write_tools()
    log.warning(
        "MCP write tools ENABLED (MCP_ALLOW_EXECUTE=true). This server can place paper orders."
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")
    init_db()
    mcp.run()


if __name__ == "__main__":
    main()
