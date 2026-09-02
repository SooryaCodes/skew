"""The core cycle.

    for symbol in universe:
        vol state  ->  regime  ->  candidates  ->  gate chain
        log every gate result, pass or fail
        if nothing survived: abstain and continue
        bounded model selects one, or abstains
        pre-flight recheck, then one atomic mleg order
    monitor open positions

Three properties worth stating, because they are what makes this a desk rather
than a script:

* **Every branch writes to the audit log.** Refusals and abstentions are
  recorded as prominently as fills. A cycle that traded nothing still produces a
  complete account of what it looked at and why it declined.
* **Nothing here can raise past one symbol.** A bad chain on NVDA must not stop
  the desk looking at SPY, so every symbol is evaluated inside its own guard and
  a failure becomes a logged abstention.
* **The kill switch halts entries only.** Monitoring keeps running, because
  looking away from open positions is not a safety feature.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler

from skew.agent.bounded import BoundedSelector, pick_candidate
from skew.audit import log as audit
from skew.config import Settings
from skew.config import settings as default_settings
from skew.data.chains import ChainClient
from skew.data.store import IVPoller
from skew.db import init_db
from skew.desk import Desk
from skew.exec import monitor
from skew.exec.exit import close_structure
from skew.exec.submit import SubmissionRefused, submit_structure
from skew.gates.base import GateContext
from skew.models import CycleReport
from skew.risk import authority
from skew.vol.term import term_structure_slope

log = logging.getLogger(__name__)

# Module-level so the API can read the last cycle without re-running one.
_LAST_CYCLE: CycleReport | None = None

# One cycle at a time, whether the scheduler or the operator asked for it.
_CYCLE_LOCK = threading.Lock()

# Live progress for the RUN CYCLE NOW control — what the desk is doing right
# now, so a visitor can watch it think instead of staring at a static page.
CYCLE_PROGRESS: dict = {
    "running": False,
    "phase": "idle",
    "symbol": None,
    "index": 0,
    "total": 0,
    "started_at": None,
    "finished_at": None,
    "error": None,
}


class CycleInProgress(RuntimeError):
    """A cycle is already running; the trigger should say so, not queue up."""


def _progress(**updates) -> None:
    CYCLE_PROGRESS.update(updates)


_DESK: Desk | None = None
_SELECTOR: BoundedSelector | None = None

# Set once by the API lifespan after the boot-time account check. suffix is the
# last four characters of the connected account id (all the API ever exposes);
# error is a competition-account mismatch, and an armed desk requires it None.
ACCOUNT: dict[str, str | float | None] = {
    "suffix": None,
    "error": None,
    "equity": None,
    # Full account number, SERVER-SIDE ONLY: stamped onto decision rows and
    # checked against the audit DB's owner. The API exposes the suffix only.
    "number": None,
    # Read from the Alpaca account object at boot — never hardcoded.
    "options_level": None,
    "starting_equity": None,
}


def _past_deadline(settings: Settings) -> bool:
    """After DEADLINE_UTC the monitor flattens the book — entries must not
    quietly rebuild it on the next cycle."""
    if not settings.deadline_utc:
        return False
    try:
        deadline = datetime.fromisoformat(settings.deadline_utc)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
    except ValueError:
        return False
    return datetime.now(UTC) >= deadline


def breaker_engaged(risk, settings: Settings) -> bool:
    """The drawdown circuit breaker, pure and testable.

    Engaged when account drawdown from peak equity meets or exceeds the
    configured threshold. A stood-down desk is the thesis working, not an
    error state.
    """
    return risk is not None and risk.drawdown_pct >= settings.drawdown_breaker_pct


# The two-instance guard, set at boot: when the broker holds option positions
# this instance's book never created, another writer owns the account. Entries
# stop; monitoring of OUR OWN positions continues.
CONFLICT: dict[str, object] = {"active": False, "foreign": [], "message": None}


def get_selector(settings: Settings | None = None) -> BoundedSelector:
    """Process-wide selector, so its last error survives for /api/status."""
    global _SELECTOR
    if _SELECTOR is None:
        _SELECTOR = BoundedSelector(settings or default_settings)
    return _SELECTOR


def get_desk(settings: Settings | None = None) -> Desk:
    """Process-wide Desk, so chain and bar caches survive between cycles."""
    global _DESK
    if _DESK is None:
        _DESK = Desk(settings=settings)
    return _DESK


def last_cycle() -> CycleReport | None:
    return _LAST_CYCLE


def run_cycle(
    dry_run: bool = True,
    settings: Settings | None = None,
    desk: Desk | None = None,
    selector: BoundedSelector | None = None,
) -> CycleReport:
    """One full pass over the universe.

    ``dry_run`` does everything except submit — the gates run, the model is
    asked, the decision is logged — so a cycle can be exercised end to end
    without touching the account.
    """
    global _LAST_CYCLE

    if not _CYCLE_LOCK.acquire(blocking=False):
        raise CycleInProgress("A cycle is already running.")

    cfg = settings or default_settings
    desk = desk or get_desk(cfg)
    selector = selector or get_selector(cfg)
    report = CycleReport(ts=datetime.now(UTC))

    _progress(
        running=True,
        phase="starting",
        symbol=None,
        index=0,
        total=0,
        started_at=report.ts.isoformat(),
        finished_at=None,
        error=None,
    )

    init_db()
    desk.start_cycle()

    # Defence in depth. The scheduler already skips closed markets, but a live
    # cycle can also be triggered by the CLI and by a redeploy, and submitting
    # into a closed market queues an order nobody is watching.
    if not dry_run and not desk.market_open():
        log.warning("market is closed — running this cycle dry rather than submitting")
        dry_run = True
        report.errors.append("market closed: cycle downgraded to dry run")

    # Monitoring first, and unconditionally. Freeing capacity before looking for
    # new positions is also what lets a full book take a better trade.
    try:
        try:
            report.decisions.extend(_monitor(desk, dry_run=dry_run, settings=cfg))
        except Exception:  # one bad monitoring pass must never stop the cycle
            log.exception("position monitoring raised — continuing with entry evaluation")
    except Exception as exc:
        log.exception("position monitoring failed")
        report.errors.append(f"monitor: {exc}")

    from skew.universe import effective_universe

    symbols = effective_universe(cfg)
    _progress(total=len(symbols))
    try:
        for index, symbol in enumerate(symbols):
            report.scanned.append(symbol)
            _progress(phase="scanning", symbol=symbol, index=index + 1)
            try:
                report.decisions.extend(
                    _evaluate_and_act(desk, selector, symbol, report, dry_run=dry_run, settings=cfg)
                )
            except Exception as exc:
                log.exception("cycle failed on %s", symbol)
                report.errors.append(f"{symbol}: {exc}")

        _LAST_CYCLE = report
        return report
    finally:
        _progress(
            running=False,
            phase="decided",
            symbol=None,
            finished_at=datetime.now(UTC).isoformat(),
        )
        _CYCLE_LOCK.release()


def _trace_for(result) -> dict:
    """The recorded reasoning chain behind one symbol's decisions this cycle.

    Every value here was observed during THIS evaluation — spot, contract
    count, the measured vols, the classifier's sentence — so a decision trace
    replays what actually happened rather than recomputing something similar.
    """
    v = result.vol_state
    if v is None:
        return {"scan": {"symbol": result.symbol, "error": result.error}}
    return {
        "scan": {
            "symbol": v.symbol,
            "spot": v.spot,
            "contracts": result.chain_contracts,
            "as_of": v.as_of.isoformat(),
        },
        "measure": {
            "iv_atm": v.iv_atm,
            "rv_20": v.rv_20,
            "rv_parkinson": v.rv_parkinson,
            "vrp": v.vrp,
            "term_slope": v.term_slope,
            "rv_percentile": v.rv_percentile,
        },
        "classify": {"regime": v.regime, "note": v.note},
        "build": {
            "count": len(result.candidates),
            "kinds": [c.structure.kind for c in result.candidates],
            "survivors": [c.id for c in result.survivors],
        },
    }


def _evaluate_and_act(
    desk: Desk,
    selector: BoundedSelector,
    symbol: str,
    report: CycleReport,
    dry_run: bool,
    settings: Settings,
):
    """Everything the desk does about one symbol in one cycle."""
    decisions = []
    result = desk.evaluate_symbol(symbol, on_stage=lambda stage: _progress(phase=stage))
    trace = _trace_for(result)
    tier = result.risk.tier

    if result.vol_state is not None:
        report.vol_states.append(result.vol_state)

    # No volatility state, or a regime that says stand down.
    if result.vol_state is None or not result.candidates:
        decisions.append(
            audit.record_abstention(
                symbol=symbol,
                reason=result.error or "No candidate could be constructed.",
                risk_tier=tier,
                detail={
                    "regime": result.vol_state.regime if result.vol_state else None,
                    "vrp": result.vol_state.vrp if result.vol_state else None,
                },
                trace=trace,
            )
        )
        return decisions

    report.candidates.extend(result.candidates)

    # Refusals are logged as prominently as executions — that is the product.
    for candidate in result.candidates:
        if not candidate.passed_all:
            decisions.append(audit.record_refusal(candidate, tier, trace=trace))

    survivors = result.survivors
    if not survivors:
        decisions.append(
            audit.record_abstention(
                symbol=symbol,
                reason=(
                    f"All {len(result.candidates)} candidates refused by the gate chain. "
                    f"No position taken."
                ),
                risk_tier=tier,
                detail={"refused": len(result.candidates)},
                trace=trace,
            )
        )
        return decisions

    # Drawdown circuit breaker: past the threshold the desk stops OPENING
    # positions — monitoring continues elsewhere — and says so as a decision.
    # Checked before the selector so a stood-down desk spends no model calls.
    if breaker_engaged(result.risk, settings):
        decisions.append(
            audit.record_abstention(
                symbol=symbol,
                reason=(
                    f"Entries paused — drawdown circuit breaker at "
                    f"{settings.drawdown_breaker_pct:.0%}. Account drawdown "
                    f"{result.risk.drawdown_pct:.1%} from peak equity. Open positions "
                    f"remain monitored; entries resume when equity recovers."
                ),
                risk_tier=tier,
                detail={
                    "drawdown_breaker": True,
                    "drawdown_pct": round(result.risk.drawdown_pct, 4),
                    "threshold": settings.drawdown_breaker_pct,
                },
                trace=trace,
            )
        )
        return decisions

    # The model sees only pre-validated candidates, and may pick one or abstain.
    _progress(phase="deciding")
    selection = selector.select(result.vol_state, survivors, result.risk)
    chosen = pick_candidate(survivors, selection)

    if chosen is None:
        decisions.append(
            audit.record_abstention(
                symbol=symbol,
                reason=(
                    f"Bounded selector abstained across {len(survivors)} approved candidate(s)."
                ),
                risk_tier=tier,
                model_rationale=selection.rationale,
                detail={
                    "malformed": selection.malformed,
                    "offered": [c.id for c in survivors],
                },
                trace=trace,
            )
        )
        return decisions

    if dry_run:
        decisions.append(
            audit.record_abstention(
                symbol=symbol,
                reason=(
                    f"DRY RUN — would have submitted {chosen.structure.describe()} for "
                    f"${abs(chosen.structure.net_credit):,.2f}, max loss "
                    f"${chosen.structure.max_loss:,.2f}. No order sent."
                ),
                risk_tier=tier,
                model_rationale=selection.rationale,
                detail={
                    "dry_run": True,
                    "structure_id": chosen.id,
                    "offered": [c.id for c in survivors],
                },
                trace=trace,
            )
        )
        return decisions

    if _past_deadline(settings):
        decisions.append(
            audit.record_abstention(
                symbol=symbol,
                reason=(
                    f"Competition window closed on 4 September — "
                    f"{len(survivors)} candidate(s) cleared every gate, but the desk no "
                    f"longer opens positions. It continues to scan, measure and log."
                ),
                risk_tier=tier,
                detail={"deadline": settings.deadline_utc},
                trace=trace,
            )
        )
        return decisions

    if ACCOUNT["error"]:
        decisions.append(
            audit.record_abstention(
                symbol=symbol,
                reason=(
                    f"Entries halted — account guard: {ACCOUNT['error']} "
                    f"Open positions remain monitored."
                ),
                risk_tier=tier,
                model_rationale=selection.rationale,
                detail={"account_guard": True},
                trace=trace,
            )
        )
        return decisions

    if CONFLICT["active"]:
        decisions.append(
            audit.record_abstention(
                symbol=symbol,
                reason=(
                    "Two-instance conflict — the account holds positions this instance "
                    "did not create. Entries halted; own positions still monitored. "
                    "Point the two instances at different accounts."
                ),
                risk_tier=tier,
                model_rationale=selection.rationale,
                detail={"instance_conflict": True, "foreign": CONFLICT["foreign"]},
                trace=trace,
            )
        )
        return decisions

    if settings.kill_switch:
        decisions.append(
            audit.record_abstention(
                symbol=symbol,
                reason="Kill switch engaged — entries halted. Open positions still monitored.",
                risk_tier=tier,
                model_rationale=selection.rationale,
                detail={"kill_switch": True},
                trace=trace,
            )
        )
        return decisions

    context = _gate_context(desk, result, settings)
    try:
        order = submit_structure(desk.broker, chosen, context, settings=settings)
    except SubmissionRefused as exc:
        # Includes the pre-flight recheck failing because the market moved.
        decisions.append(
            audit.record_refusal(
                chosen,
                tier,
                extra={"submission_refused": str(exc), "stage": "pre-flight"},
                trace=trace,
            )
        )
        return decisions

    # The position exists when the broker says it does, not when we asked.
    # An unfilled submission stays an OrderRow; reconciliation promotes it to
    # a position if it fills later, or writes a correction if it dies.
    filled = _await_fill(desk.broker, order["client_order_id"])
    if filled:
        monitor.record_open(chosen.structure, order["client_order_id"])
    decisions.append(
        audit.record_execution(
            chosen,
            tier,
            order_id=order["client_order_id"],
            model_rationale=selection.rationale,
            detail={
                "broker_order_id": order.get("broker_order_id"),
                "status": "filled" if filled else order.get("status"),
                "fill_confirmed": filled,
                "offered": [c.id for c in survivors],
            },
            trace=trace,
        )
    )
    return decisions


def _gate_context(desk: Desk, result, settings: Settings) -> GateContext:
    """Rebuild the gate context for the pre-flight recheck, on fresh quotes."""
    cfg = settings
    chain = desk.chains.get_chain(
        result.symbol,
        dte_min=cfg.target_dte_min,
        dte_max=max(cfg.target_dte_max + 60, cfg.term_far_target_dte + 20),
        use_cache=False,
    )
    return GateContext(
        vol_state=result.vol_state,
        risk=result.risk,
        realized_vol=result.vol_state.rv_20,
        term=term_structure_slope(
            chain,
            near_target_dte=(cfg.target_dte_min + cfg.target_dte_max) // 2,
            far_target_dte=cfg.term_far_target_dte,
            backwardation_floor=cfg.term_backwardation_floor,
        ),
        earnings=desk.earnings,
        as_of=datetime.now(UTC).date(),
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


def _monitor(desk: Desk, dry_run: bool, settings: Settings):
    """Check open positions and close the ones that have hit a rule.

    Reconciliation runs FIRST: the broker is the truth, and exit rules must
    never fire on a position the broker does not hold. See exec/reconcile.py.
    """
    from skew.exec.reconcile import broker_holds_legs, reconcile

    decisions = []
    try:
        report = reconcile(desk.broker)
        if report["corrected"]:
            log.warning("reconciliation corrected %d record(s): %s",
                        len(report["corrected"]), report["corrected"])
    except Exception:  # a failed reconcile pass must not stop monitoring
        log.exception("reconciliation pass raised")

    actions = monitor.monitor_positions(desk.broker, settings=settings)
    tier = authority.evaluate_tier(desk.equity())

    for action in actions:
        if dry_run:
            decisions.append(
                audit.record_abstention(
                    symbol=action["symbol"],
                    reason=f"DRY RUN — would close on {action['rule']}: {action['reason']}",
                    risk_tier=tier,
                    detail={"dry_run": True, "structure_id": action["structure_id"]},
                )
            )
            continue

        # The precondition for any close: the broker actually holds the legs.
        # 28 rejected SPY closes fired on a phantom before this check existed.
        if not broker_holds_legs(desk.broker, action["structure"]):
            log.warning(
                "close skipped — broker does not hold the legs of %s; "
                "reconciliation will correct the record next pass",
                action["structure_id"],
            )
            continue

        if _close_already_resting(action["structure_id"]):
            log.info("close for %s already resting at the broker; not resubmitting",
                     action["structure_id"])
            continue

        try:
            order = close_structure(
                desk.broker,
                action["structure"],
                current_mids=action["mids"],
                reason=action["reason"],
                settings=settings,
            )
        except Exception as exc:
            log.exception("failed to close %s", action["structure_id"])
            decisions.append(
                audit.record(
                    action="REFUSED",
                    reason=f"Could not close {action['symbol']}: {exc}",
                    risk_tier=tier,
                    symbol=action["symbol"],
                    structure_id=action["structure_id"],
                )
            )
            continue

        # The book records the close only when the broker confirms the fill —
        # a close is a submission until then, exactly like an open.
        filled = _await_fill(desk.broker, order["client_order_id"])
        if filled:
            monitor.record_close(
                action["structure_id"], action["unrealized_pnl"], action["reason"]
            )
            # A position closed on the loss limit is not a gate breach — the
            # gates held and the structure stayed inside its defined risk.
            # Only a genuine breach demotes.
            authority.record_closed_trade(clean=action["rule"] != "breach")
        decisions.append(
            audit.record(
                action="EXECUTED",
                reason=(
                    f"Closed on {action['rule']}: {action['reason']}"
                    if filled
                    else f"Submitted close on {action['rule']} — awaiting fill: "
                    f"{action['reason']}"
                ),
                risk_tier=tier,
                symbol=action["symbol"],
                structure_id=action["structure_id"],
                order_id=order["client_order_id"],
                detail={
                    "realized_pnl": action["unrealized_pnl"] if filled else None,
                    "rule": action["rule"],
                    "fill_confirmed": filled,
                },
            )
        )
    return decisions


def _close_already_resting(structure_id: str) -> bool:
    from sqlalchemy import select

    from skew.audit.models import OrderRow
    from skew.db import session_scope
    from skew.exec.submit import RESTING_OR_FILLED

    with session_scope() as session:
        orders = session.scalars(
            select(OrderRow).where(
                OrderRow.structure_id == f"{structure_id}:CLOSE", OrderRow.intent == "CLOSE"
            )
        ).all()
        return any((o.status or "").lower() in RESTING_OR_FILLED - {"filled"} for o in orders)


def _await_fill(broker, client_order_id: str, attempts: int = 4, wait_s: float = 4.0) -> bool:
    """Poll briefly for a fill. Closes are priced at the live mid, so most fill
    in seconds; one that does not is finished by reconciliation next cycle."""
    import time as _time

    for _ in range(attempts):
        try:
            order = broker.get_order_by_client_id(client_order_id)
            status = str(getattr(order, "status", "")).lower()
            if "filled" in status and "partially" not in status:
                _update_order_status(client_order_id, "filled")
                return True
            if any(dead in status for dead in ("canceled", "expired", "rejected")):
                _update_order_status(client_order_id, status.replace("orderstatus.", ""))
                return False
        except Exception:  # noqa: BLE001 — polling is best-effort
            pass
        _time.sleep(wait_s)
    return False


def _update_order_status(client_order_id: str, status: str) -> None:
    from skew.audit.models import OrderRow
    from skew.db import session_scope

    with session_scope() as session:
        row = session.get(OrderRow, client_order_id)
        if row is not None:
            row.status = status


# ------------------------------------------------------------------ scheduler


def build_scheduler(settings: Settings | None = None) -> BackgroundScheduler:
    """APScheduler with the trading cycle and the IV poller.

    The two run on separate intervals deliberately. The trading loop only acts
    during the regular session; the IV poller keeps sampling regardless, because
    the history it is building is the only IV history that will ever exist —
    Alpaca serves none.
    """
    cfg = settings or default_settings
    scheduler = BackgroundScheduler(timezone="UTC")
    desk = get_desk(cfg)

    def trading_tick() -> None:
        if not desk.market_open():
            log.debug("market closed — skipping trading cycle")
            return
        try:
            report = run_cycle(dry_run=False, settings=cfg, desk=desk)
            log.info(
                "cycle: %d scanned, %d candidates, %d decisions, %d errors",
                len(report.scanned),
                len(report.candidates),
                len(report.decisions),
                len(report.errors),
            )
        except Exception:
            log.exception("trading cycle raised")

    poller = IVPoller(ChainClient(desk.broker), cfg.universe_symbols)

    def iv_tick() -> None:
        try:
            from skew.universe import effective_universe

            poller.symbols = effective_universe(cfg)
            stored = poller.poll_once()
            log.debug("IV poll stored %d symbols", len(stored))
        except Exception:
            log.exception("IV poll raised")

    scheduler.add_job(
        trading_tick,
        "interval",
        seconds=cfg.loop_interval_seconds,
        id="trading_cycle",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        iv_tick,
        "interval",
        seconds=cfg.iv_poll_interval_seconds,
        id="iv_poller",
        max_instances=1,
        coalesce=True,
    )
    return scheduler
