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
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Request
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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start the desk alongside the API.

    The trading loop needs a persistent process — that is why this deploys to a
    container rather than to serverless — so it runs here rather than in a
    separate service. The first cycle is kicked off immediately, in the
    scheduler's own thread, so the dashboard has something to render within a
    few seconds of boot instead of waiting for the first interval.
    """
    init_db()
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
        "universe": settings.universe_symbols,
        "last_cycle": report.ts.isoformat() if report else None,
        "auto_execute": settings.auto_execute,
        "scheduler_running": settings.run_scheduler,
        # An armed desk whose selection step is unreachable looks exactly like a
        # calm market from outside. Say so plainly rather than making an
        # operator read logs to find out nothing can trade.
        "selector_error": loop.get_selector().last_error,
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


@api.post("/kill", summary="Kill switch — halts new entries. Requires auth.")
@limiter.limit("10/minute")
def post_kill(
    request: Request,
    engage: bool = Query(default=True),
    x_admin_token: str = Header(default=""),
) -> dict[str, Any]:
    """Halt new entries immediately. Monitoring of open positions continues.

    Authenticated with a shared secret, compared in constant time. Also settable
    by environment variable so the state survives a restart.
    """
    expected = settings.admin_token
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_TOKEN is not configured, so the kill switch cannot be authenticated.",
        )
    if not secrets.compare_digest(x_admin_token or "", expected):
        raise HTTPException(status_code=401, detail="Invalid admin token.")

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
