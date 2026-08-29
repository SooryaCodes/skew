"""The read-only API the frontend consumes.

docs/05-SECURITY.md: **the Alpaca key never reaches the browser.** The Next.js
app talks only to this service and holds no credential of any kind. Every
endpoint below is read-only and exposes no secret and no account identifier,
with exactly one exception — ``POST /api/kill``, which is authenticated with a
shared secret.

Rate limited, because a public demo URL gets scraped.
"""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from skew import loop
from skew.audit import log as audit
from skew.config import PAPER_HOST, settings
from skew.data.store import daily_closing_iv, history_window_days, observation_count
from skew.db import init_db
from skew.exec import monitor
from skew.models import Candidate, Decision, Position, RiskAuthority, VolState

log = logging.getLogger(__name__)

VERSION = "0.1.0"

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])

# Cache of the last full scan, so the dashboard polling every 5s does not drive
# a chain fetch per request. Refreshed by the loop; served as-is between cycles.
_CACHE: dict[str, Any] = {"vol_states": [], "candidates": [], "as_of": None}


def _configure_logging() -> None:
    """Give the skew loggers a real handler.

    Uvicorn configures only its own loggers, and Python silently drops INFO
    records from unconfigured ones — which meant the selector preflight result
    and every cycle summary vanished. Operational logs the operator cannot see
    are how a desk burns a day looking healthy.
    """
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        root.addHandler(handler)
    root.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start the desk alongside the API.

    The trading loop needs a persistent process — that is why this deploys to a
    container rather than to serverless — so it runs here rather than in a
    separate service. The first cycle is kicked off immediately, in the
    scheduler's own thread, so the dashboard has something to render within a
    few seconds of boot instead of waiting for the first interval.
    """
    _configure_logging()
    init_db()

    # Preflight the bounded selector with one cheap real call. An armed desk
    # whose selection step cannot be reached would otherwise abstain its way
    # through an entire market day while looking exactly like a calm market.
    # A failure here is loud, and the desk refuses to report itself as armed.
    from skew.agent.bounded import preflight

    error = preflight(settings)
    loop.get_selector(settings).last_error = error
    if error:
        log.error("SELECTOR PREFLIGHT FAILED — the desk will NOT trade: %s", error)
    else:
        log.info("selector preflight ok — model %s reachable", settings.anthropic_model)

    scheduler = None
    if settings.run_scheduler:
        from datetime import timedelta

        from skew.loop import build_scheduler, run_cycle

        scheduler = build_scheduler(settings)
        # The startup cycle is ALWAYS dry. Its job is to populate the dashboard
        # within a few seconds of boot, not to trade — and it does not check
        # market hours, so letting it submit would mean a deploy at 3am placing
        # orders. The scheduled ticks do the trading, and they check.
        scheduler.add_job(
            lambda: run_cycle(dry_run=True, settings=settings),
            "date",
            run_date=datetime.now(UTC) + timedelta(seconds=2),
            id="startup_cycle",
        )
        scheduler.start()
        log.info(
            "scheduler started — %ss cycle, auto_execute=%s",
            settings.loop_interval_seconds,
            settings.auto_execute,
        )

    log.info("SKEW API up — paper-only, base URL %s", settings.alpaca_base_url)
    yield

    if scheduler is not None:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="SKEW",
    description=(
        "An autonomous options volatility desk. Measures the gap between implied and "
        "realized volatility and takes defined-risk positions into it. Paper trading only — "
        "there is no live-trading code path."
    ),
    version=VERSION,
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Permissive CORS is acceptable for read-only endpoints; the single write
# endpoint is protected by a shared secret rather than by origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api")


def require_operator(
    x_operator_token: str = Header(default=""),
    x_admin_token: str = Header(default=""),
) -> None:
    """Auth for every ACTION endpoint. Reads stay fully public.

    No accounts and no login wall — this is a single-operator desk, and judges
    must reach the dashboard in one click. A shared token in a header, compared
    in constant time, is the entire ceremony. ADMIN_TOKEN is a legacy alias.
    """
    expected = settings.operator_token or settings.admin_token
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="OPERATOR_TOKEN is not configured, so action endpoints are disabled.",
        )
    provided = x_operator_token or x_admin_token
    if not secrets.compare_digest(provided or "", expected):
        raise HTTPException(status_code=401, detail="Invalid operator token.")


def _refresh_cache() -> None:
    """Pull the latest cycle's view into the cache."""
    report = loop.last_cycle()
    if report is None:
        return
    _CACHE["vol_states"] = report.vol_states
    _CACHE["candidates"] = report.candidates
    _CACHE["as_of"] = report.ts


def _states() -> list[VolState]:
    _refresh_cache()
    return list(_CACHE.get("vol_states") or [])


def _candidates() -> list[Candidate]:
    _refresh_cache()
    return list(_CACHE.get("candidates") or [])


def _risk() -> RiskAuthority:
    from skew.risk import authority

    desk = loop.get_desk()
    used, open_count = authority.committed_dollars()
    return authority.get_authority(desk.equity(), used_dollars=used, open_positions=open_count)


# ------------------------------------------------------------------ endpoints


@api.get("/status", summary="System status and the paper-only guarantee")
def get_status() -> dict[str, Any]:
    desk = loop.get_desk()
    report = loop.last_cycle()
    market_open = False
    try:
        market_open = desk.market_open()
    except Exception as exc:  # noqa: BLE001 — status must never 500
        log.warning("market status unavailable: %s", exc)

    from skew.data.calendar import EASTERN, is_trading_day
    from skew.universe import effective_universe

    # The most recent trading session: today when the market has opened at all
    # today, otherwise walk back. This is what the closed-market header names.
    eastern_today = datetime.now(UTC).astimezone(EASTERN).date()
    session_day = eastern_today
    while not is_trading_day(session_day):
        session_day -= timedelta(days=1)

    return {
        "ok": True,
        # Not a computed value. There is no configuration of this service that
        # can trade anywhere but the paper endpoint.
        "paper_only": True,
        "base_url": PAPER_HOST,
        "kill_switch": settings.kill_switch,
        "market_open": market_open,
        "broker_connected": desk.broker.available,
        "model_connected": settings.has_model_credentials,
        "universe": effective_universe(settings),
        "last_session": session_day.isoformat(),
        "last_cycle": report.ts.isoformat() if report else None,
        "auto_execute": settings.auto_execute,
        "scheduler_running": settings.run_scheduler,
        # An armed desk whose selection step is unreachable looks exactly like a
        # calm market from outside. selector_error carries the specific failure
        # (status code and body, not an exception class), and "armed" is the
        # server's own verdict: configured to trade AND the selector answered
        # the startup preflight. The UI renders armed only from this field.
        "selector_error": loop.get_selector().last_error,
        "armed": settings.auto_execute and loop.get_selector().last_error is None,
        "version": VERSION,
    }


@api.get("/universe", summary="Volatility state per symbol")
def get_universe() -> list[VolState]:
    return _states()


@api.get("/universe/{symbol}", summary="Volatility state for one symbol")
def get_symbol(symbol: str) -> VolState:
    for state in _states():
        if state.symbol == symbol.upper():
            return state
    raise HTTPException(status_code=404, detail=f"No volatility state for {symbol.upper()} yet.")


@api.get("/candidates", summary="Current candidates with full gate results")
def get_candidates(symbol: str | None = Query(default=None)) -> list[Candidate]:
    candidates = _candidates()
    if symbol:
        candidates = [c for c in candidates if c.structure.symbol == symbol.upper()]
    return candidates


@api.get("/stress/{candidate_id:path}", summary="The 84-cell stress grid for one candidate")
def get_stress(candidate_id: str) -> dict[str, Any]:
    for candidate in _candidates():
        if candidate.id == candidate_id:
            return {
                "candidate_id": candidate.id,
                "symbol": candidate.structure.symbol,
                "kind": candidate.structure.kind,
                "max_loss": candidate.structure.max_loss,
                "worst_case": candidate.worst_case,
                "cells": candidate.stress_grid,
            }
    raise HTTPException(status_code=404, detail=f"No candidate {candidate_id}.")


@api.get("/positions", summary="Open positions, marked to market")
def get_positions() -> list[Position]:
    rows = monitor.open_positions()
    if not rows:
        return []
    contracts = sorted({s for row in rows for s in (row.legs or [])})
    mids = monitor.fetch_mids(loop.get_desk().broker, contracts)
    return [monitor.to_position(row, mids) for row in rows]


@api.get("/risk", summary="Earned risk tier, budget and drawdown")
def get_risk() -> RiskAuthority:
    return _risk()


@api.get("/audit", summary="The decision stream — refusals as prominent as fills")
def get_audit(
    limit: int = Query(default=50, ge=1, le=500),
    action: str | None = Query(default=None, pattern="^(EXECUTED|REFUSED|ABSTAINED)$"),
) -> list[Decision]:
    return audit.recent(limit=limit, action=action)  # type: ignore[arg-type]


@api.get("/audit/counts", summary="Executions vs refusals vs abstentions")
def get_audit_counts(since_hours: int | None = Query(default=None, ge=1, le=8760)):
    return audit.counts(since_hours=since_hours)


@api.get("/iv-history/{symbol}", summary="Self-collected ATM IV history")
def get_iv_history(symbol: str) -> dict[str, Any]:
    """Alpaca serves no historical IV. This is what we have built since first run.

    ``window_days`` and ``observations`` are returned alongside the series so the
    UI can label it honestly and never present a short window as a long one.
    """
    key = symbol.upper()
    series = daily_closing_iv(key)
    return {
        "symbol": key,
        "window_days": history_window_days(key),
        "observations": observation_count(key),
        "series": [{"date": d, "atm_iv": iv} for d, iv in series],
        "note": (
            "Built forward from first run. Alpaca serves no historical implied "
            "volatility, so this is not a 52-week series and is not presented as one."
        ),
    }


@api.get("/vrp-history/{symbol}", summary="IV vs RV, day by day, since first run")
def get_vrp_history(symbol: str) -> dict[str, Any]:
    """The variance risk premium over time: daily closing ATM IV against the
    20-day realized vol on the same date.

    The IV side comes from the snapshot poller and exists only since first run —
    Alpaca serves no historical IV — so the window is labelled with exactly how
    much history it holds and never implies more. The RV side is computed from
    bar history and aligned by date.
    """
    key = symbol.upper()
    iv_days = daily_closing_iv(key)

    rv_by_date: dict[str, float] = {}
    try:
        from skew.vol.realized import rolling_close_to_close

        bars = loop.get_desk().bars.get_bars(key)
        series = rolling_close_to_close(bars.closes, window=20)
        # rolling series index i corresponds to the (window + i)-th close.
        dates = [b.date.isoformat() for b in bars.bars]
        offset = len(dates) - len(series)
        for i, value in enumerate(series):
            rv_by_date[dates[offset + i]] = float(value)
    except Exception as exc:  # noqa: BLE001 — IV side still renders without RV
        log.warning("vrp-history: realized side unavailable for %s: %s", key, exc)

    def rv_on_or_before(day: str) -> float | None:
        # Weekend IV samples pair with the last trading day's realized vol.
        candidates = [d for d in rv_by_date if d <= day]
        return rv_by_date[max(candidates)] if candidates else None

    return {
        "symbol": key,
        "window_days": history_window_days(key),
        "observations": observation_count(key),
        "series": [{"date": d, "iv": iv, "rv": rv_on_or_before(d)} for d, iv in iv_days],
        "note": (
            "IV history is built forward from first run — Alpaca serves none. "
            "This window is exactly as long as it says it is."
        ),
    }


@api.get("/cycle/status", summary="What the desk is doing right now")
def get_cycle_status() -> dict[str, Any]:
    """Live progress of the running cycle, and a summary of the last one.

    Public: watching the desk think is the product's best demo, and reads cost
    nothing.
    """
    report = loop.last_cycle()
    return {
        "progress": dict(loop.CYCLE_PROGRESS),
        "last_cycle": (
            {
                "ts": report.ts.isoformat(),
                "scanned": len(report.scanned),
                "candidates": len(report.candidates),
                "decisions": len(report.decisions),
                "errors": len(report.errors),
            }
            if report
            else None
        ),
    }


@api.post(
    "/cycle",
    summary="Run a cycle now. Requires the operator token.",
    dependencies=[Depends(require_operator)],
)
@limiter.limit("6/minute")
def post_cycle(request: Request) -> dict[str, Any]:
    """Trigger an immediate scan in the background.

    The cycle honours every safety rule the scheduled one does: it downgrades
    itself to a dry run when the market is closed, re-runs gates before any
    submission, and respects the kill switch. Poll /api/cycle/status to watch.
    """
    if loop.CYCLE_PROGRESS.get("running"):
        raise HTTPException(status_code=409, detail="A cycle is already running.")

    def _run() -> None:
        try:
            loop.run_cycle(dry_run=not settings.auto_execute, settings=settings)
        except loop.CycleInProgress:
            pass  # lost the race to the scheduler's tick — that cycle serves
        except Exception:
            log.exception("operator-triggered cycle failed")
            loop.CYCLE_PROGRESS.update(running=False, phase="error")

    import threading

    threading.Thread(target=_run, name="operator-cycle", daemon=True).start()
    audit.record(
        action="ABSTAINED",
        reason="Operator triggered an immediate cycle.",
        risk_tier=_risk().tier,
        detail={"source": "operator"},
    )
    return {"started": True}


@api.post(
    "/universe",
    summary="Add or remove a symbol. Requires the operator token.",
    dependencies=[Depends(require_operator)],
)
@limiter.limit("20/minute")
def post_universe(
    request: Request,
    symbol: str = Query(min_length=1, max_length=8),
    action: str = Query(pattern="^(add|remove)$"),
) -> dict[str, Any]:
    """Edit the universe. Persisted; takes effect on the next cycle.

    This is the entire scope of runtime configuration. Risk tiers, budgets and
    gate thresholds are deliberately not editable — an editable limit is not an
    earned one.
    """
    from skew import universe

    try:
        symbols = (
            universe.add_symbol(symbol, settings)
            if action == "add"
            else universe.remove_symbol(symbol, settings)
        )
    except universe.UniverseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    audit.record(
        action="ABSTAINED",
        reason=f"Operator {'added' if action == 'add' else 'removed'} "
        f"{universe.validate_symbol(symbol)} — universe is now {', '.join(symbols)}. "
        f"Takes effect next cycle.",
        risk_tier=_risk().tier,
        detail={"source": "operator", "universe": symbols},
    )
    return {"universe": symbols, "effective": "next cycle"}


@api.get("/session", summary="The shape of the most recent session")
def get_session() -> dict[str, Any]:
    """A working day at a glance: what was scanned, built, refused, executed —
    plus the most recent fill ever, which is the proof the submission rests on.
    """
    from skew.data.calendar import EASTERN, is_trading_day

    eastern_now = datetime.now(UTC).astimezone(EASTERN)
    session_day = eastern_now.date()
    while not is_trading_day(session_day):
        session_day -= timedelta(days=1)
    session_start = datetime.combine(session_day, datetime.min.time(), tzinfo=EASTERN)

    counts = audit.counts_since(session_start.astimezone(UTC))
    report = loop.last_cycle()
    last_fill = audit.recent(limit=1, action="EXECUTED")

    market_open = False
    try:
        market_open = loop.get_desk().market_open()
    except Exception as exc:  # noqa: BLE001 — the summary must never 500
        log.warning("session summary: market state unavailable: %s", exc)

    return {
        "session_date": session_day.isoformat(),
        "market_open": market_open,
        "scanned": len(report.scanned) if report else 0,
        "candidates_built": len(report.candidates) if report else 0,
        "survivors": (sum(1 for c in report.candidates if c.passed_all) if report else 0),
        "counts": counts,
        "as_of": report.ts.isoformat() if report else None,
        "last_fill": (
            {
                "ts": last_fill[0].ts.isoformat(),
                "symbol": last_fill[0].symbol,
                "reason": last_fill[0].reason,
                "model_rationale": last_fill[0].model_rationale,
                "order_id": last_fill[0].order_id,
            }
            if last_fill
            else None
        ),
    }


@api.post(
    "/kill",
    summary="Kill switch — halts new entries. Requires auth.",
    dependencies=[Depends(require_operator)],
)
@limiter.limit("10/minute")
def post_kill(request: Request, engage: bool = Query(default=True)) -> dict[str, Any]:
    """Halt new entries immediately. Monitoring of open positions continues.

    Authenticated with the operator token, compared in constant time. Also
    settable by environment variable so the state survives a restart.
    """
    settings.kill_switch = bool(engage)
    audit.record(
        action="REFUSED" if engage else "ABSTAINED",
        reason=(
            "Kill switch ENGAGED — no new entries. Open positions continue to be monitored."
            if engage
            else "Kill switch released — entries resume."
        ),
        risk_tier=_risk().tier,
        detail={"kill_switch": settings.kill_switch, "source": "api"},
    )
    log.warning("kill switch set to %s via API", settings.kill_switch)
    return {"kill_switch": settings.kill_switch, "at": datetime.now(UTC).isoformat()}


app.include_router(api)


@app.get("/", include_in_schema=False)
def root() -> JSONResponse:
    return JSONResponse(
        {
            "name": "SKEW",
            "description": "An autonomous options volatility desk. Paper trading only.",
            "paper_only": True,
            "docs": "/docs",
            "api": "/api/status",
        }
    )


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}
