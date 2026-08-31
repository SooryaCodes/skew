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

    # Boot-time account check: log who we are connected as, warn on a drifted
    # balance, and refuse to arm on the wrong account. Unreachable-broker boots
    # (no credentials, network down) leave suffix None; if a competition id is
    # configured, unverified counts as failed — never arm on an unknown account.
    desk = loop.get_desk(settings)
    if desk.broker.available:
        try:
            check = desk.broker.verify_account()
            loop.ACCOUNT["suffix"] = check.get("account_id_suffix")
            loop.ACCOUNT["number"] = check.get("account_number")
            loop.ACCOUNT["equity"] = check.get("equity")
            loop.ACCOUNT["options_level"] = check.get("options_approved") or check.get(
                "options_level"
            )
            loop.ACCOUNT["error"] = check.get("competition_error")
            if loop.ACCOUNT["error"] is None:
                loop.ACCOUNT["error"] = _claim_audit_db(str(check.get("account_number") or ""))
        except Exception as exc:  # boot must survive to report itself
            log.exception("account verification failed at boot")
            if settings.competition_account_id:
                loop.ACCOUNT["error"] = f"account unverifiable at boot: {exc}"
    elif settings.competition_account_id:
        loop.ACCOUNT["error"] = (
            "COMPETITION_ACCOUNT_ID is set but no broker credentials are configured."
        )

    # Two-instance guard: option positions at the broker that our book never
    # created mean another instance is writing to this account. Refuse to open
    # anything new; keep monitoring our own book; say so loudly.
    if desk.broker.available:
        from skew.exec.guard import foreign_option_symbols, our_leg_symbols

        try:
            foreign = foreign_option_symbols(desk.broker.list_positions(), our_leg_symbols())
        except Exception:  # status must reflect the failure, not hide it
            log.exception("two-instance guard could not read broker positions at boot")
            foreign = []
        if foreign:
            loop.CONFLICT.update(
                active=True,
                foreign=foreign,
                message=(
                    f"{len(foreign)} open option position(s) at the broker were not "
                    "created by this instance. Another desk is writing to this "
                    "account — entries are halted until they are separated."
                ),
            )
            log.error(
                "TWO-INSTANCE CONFLICT — foreign positions %s. Entries halted; "
                "monitoring continues.",
                foreign,
            )

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


START_TIME = datetime.now(UTC)


def _claim_audit_db(connected: str) -> str | None:
    """One audit DB, one account — refuse to mix decision histories.

    The first armed boot writes the connected account's id into the DB. Every
    later boot must match it; a mismatch refuses to arm and says exactly how
    to proceed (fresh DATABASE_URL, or archive the file). The dev account's
    history must never bleed into the competition account's log.
    """
    if not connected:
        return None
    from skew.audit.models import KVRow
    from skew.db import session_scope

    key = "audit_db_account"
    with session_scope() as session:
        row = session.get(KVRow, key)
        if row is None:
            # The claim also freezes the STARTING equity: the denominator every
            # later drawdown figure is honest against.
            starting = loop.ACCOUNT.get("equity")
            session.add(KVRow(key=key, value={"account": connected, "starting_equity": starting}))
            loop.ACCOUNT["starting_equity"] = starting
            log.info("audit DB claimed by account …%s", connected[-4:])
            return None
        owner = str((row.value or {}).get("account") or "")
        recorded_start = (row.value or {}).get("starting_equity")
        if recorded_start is None and owner == connected:
            # Claims written before starting_equity existed: backfill from the
            # risk state's peak, which the first-ever equity record set.
            try:
                from skew.risk.authority import _state_row

                recorded_start = float(_state_row(session).peak_equity or 0) or None
            except Exception:  # noqa: BLE001
                recorded_start = None
            if recorded_start is not None:
                row.value = {**(row.value or {}), "starting_equity": recorded_start}
        if recorded_start is not None:
            loop.ACCOUNT["starting_equity"] = recorded_start
        if owner and owner != connected:
            return (
                f"This audit DB belongs to account …{owner[-4:]} but the connected "
                f"account is …{connected[-4:]}. Refusing to mix decision histories — "
                f"point DATABASE_URL at a fresh file (the old one stays as the archive) "
                f"or restore the original credentials."
            )
    return None


def _live_equity() -> float | None:
    """Current account equity, from the broker via the desk's per-cycle cache."""
    try:
        desk = loop.get_desk()
        if not desk.broker.available:
            return None
        return round(desk.equity(), 2)
    except Exception:  # noqa: BLE001 — status must never 500
        return None


def _drawdown_paused() -> bool:
    """Whether the drawdown circuit breaker currently halts entries."""
    try:
        from skew.loop import breaker_engaged

        desk = loop.get_desk()
        return breaker_engaged(desk.risk_authority(), settings)
    except Exception:  # noqa: BLE001 — status must never 500
        return False


@api.get("/health", summary="Liveness: last cycle and uptime")
def get_health() -> dict[str, Any]:
    """The unattended-judging heartbeat: alive, when it last thought, for how
    long it has been up. Cheap enough for a platform healthcheck."""
    report = loop.last_cycle()
    return {
        "status": "ok",
        "last_cycle_at": report.ts.isoformat() if report else None,
        "uptime_seconds": round((datetime.now(UTC) - START_TIME).total_seconds()),
    }


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
        "universe_size": len(effective_universe(settings)),
        "last_session": session_day.isoformat(),
        "last_cycle": report.ts.isoformat() if report else None,
        "last_cycle_at": report.ts.isoformat() if report else None,
        # Whether the desk has EVER published a volatility state — the frontend
        # separates "not armed" from "armed, first cycle pending" with this.
        "has_published_state": bool(_states()),
        "selector_configured": settings.has_model_credentials,
        "auto_execute": settings.auto_execute,
        "scheduler_running": settings.run_scheduler,
        # An armed desk whose selection step is unreachable looks exactly like a
        # calm market from outside. selector_error carries the specific failure
        # (status code and body, not an exception class), and "armed" is the
        # server's own verdict: configured to trade AND the selector answered
        # the startup preflight. The UI renders armed only from this field.
        "selector_error": loop.get_selector().last_error,
        # Last four characters only — enough to confirm WHICH account from the
        # deployed status page, never the full id.
        "account_id_suffix": loop.ACCOUNT["suffix"],
        "account_error": loop.ACCOUNT["error"],
        # Provenance, all read from the broker at boot — none hardcoded, and
        # an unknown value stays null so the UI says "unavailable" rather than
        # substituting a default.
        "equity": _live_equity(),
        "starting_equity": loop.ACCOUNT.get("starting_equity"),
        "options_approval_level": loop.ACCOUNT.get("options_level"),
        "endpoint_is_paper": True,
        "instance_conflict": loop.CONFLICT["message"],
        "drawdown_paused": _drawdown_paused(),
        # The standing exit rules, so the positions view can print each
        # position's own exit conditions instead of a vague promise.
        "exit_rules": {
            "profit_target_pct": settings.profit_target_pct,
            "loss_limit_multiple": settings.loss_limit_multiple,
            "exit_dte_threshold": settings.exit_dte_threshold,
            "deadline_utc": settings.deadline_utc or None,
        },
        "armed": (
            settings.auto_execute
            and loop.get_selector().last_error is None
            and loop.ACCOUNT["error"] is None
        ),
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
    from skew.data.store import distinct_history_days, history_span

    first_ts, last_ts = history_span(key)
    return {
        "symbol": key,
        "window_days": history_window_days(key),
        "distinct_days": distinct_history_days(key),
        "first_ts": first_ts.isoformat() if first_ts else None,
        "last_ts": last_ts.isoformat() if last_ts else None,
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

    from skew.data.store import distinct_history_days, history_span

    first_ts, last_ts = history_span(key)
    return {
        "symbol": key,
        "window_days": history_window_days(key),
        "distinct_days": distinct_history_days(key),
        "first_ts": first_ts.isoformat() if first_ts else None,
        "last_ts": last_ts.isoformat() if last_ts else None,
        "observations": observation_count(key),
        "series": [{"date": d, "iv": iv, "rv": rv_on_or_before(d)} for d, iv in iv_days],
        "note": (
            "IV history is built forward from first run — Alpaca serves none. "
            "This window is exactly as long as it says it is."
        ),
    }


@api.get("/positions/closed", summary="Closed trades, with realized P&L")
def get_closed_positions() -> list[dict[str, Any]]:
    """The full lifecycle record: every structure this desk opened and closed.

    Realized P&L per trade, holding period, and WHICH rule closed it — the
    exit reason is the point, not the dollar figure.
    """
    from sqlalchemy import select

    from skew.audit.models import PositionRow
    from skew.db import session_scope

    out: list[dict[str, Any]] = []
    with session_scope() as session:
        rows = session.scalars(
            select(PositionRow)
            .where(PositionRow.is_open.is_(False))
            .order_by(PositionRow.closed_at.desc())
        ).all()
        for row in rows:
            opened = row.opened_at
            closed = row.closed_at
            days = None
            if opened is not None and closed is not None:
                days = round(
                    (closed.replace(tzinfo=UTC) if closed.tzinfo is None else closed).timestamp()
                    - (opened.replace(tzinfo=UTC) if opened.tzinfo is None else opened).timestamp(),
                )
                days = round(days / 86400, 1)
            out.append(
                {
                    "id": row.id,
                    "symbol": row.symbol,
                    "kind": row.kind,
                    "legs": list(row.legs or []),
                    "qty": row.qty,
                    "opened_at": opened.isoformat() if opened else None,
                    "closed_at": closed.isoformat() if closed else None,
                    "entry_credit": row.entry_credit,
                    "max_loss": row.max_loss,
                    "realized_pnl": row.realized_pnl,
                    "exit_reason": row.exit_reason,
                    "days_held": days,
                }
            )
    return out


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


# The full volatility surface is a landing-page visual: one wide chain fetch
# (out to ~370 days) per symbol, cached hard because term structure moves
# slowly and the page must never trigger a fetch storm.
_SURFACE_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_SURFACE_TTL_SECONDS = 900


@api.get("/surface/{symbol}", summary="The volatility surface — one skew curve per expiry")
def get_surface(symbol: str) -> dict[str, Any]:
    """Up to 30 real skew slices from 7 to ~365 days out, for the hero surface.

    Real chain data, same source as the desk. Cached for fifteen minutes; when
    the broker is unreachable the response says so rather than inventing a
    surface.
    """
    import time as _time

    from skew.vol.implied import skew_slice

    key = symbol.upper()
    hit = _SURFACE_CACHE.get(key)
    if hit and (_time.monotonic() - hit[0]) < _SURFACE_TTL_SECONDS:
        return {"symbol": key, "slices": hit[1], "cached": True}

    desk = loop.get_desk()
    try:
        spot = desk.broker.fetch_spot(key)
        today = datetime.now(UTC).date()
        snapshots = desk.broker.fetch_option_chain(
            key,
            expiry_gte=today + timedelta(days=5),
            expiry_lte=today + timedelta(days=370),
            strike_gte=spot * 0.88,
            strike_lte=spot * 1.12,
        )
        from skew.data.chains import build_chain

        chain = build_chain(key, spot, snapshots)
    except Exception as exc:  # noqa: BLE001 — the page degrades, never invents
        log.warning("surface unavailable for %s: %s", key, exc)
        return {"symbol": key, "slices": [], "error": "surface unavailable"}
    if spot <= 0:
        return {"symbol": key, "slices": [], "error": "surface unavailable"}

    slices: list[dict[str, Any]] = []
    for expiry in chain.expiries:
        dte = (expiry - datetime.now(UTC).date()).days
        if dte < 5 or dte > 370:
            continue
        # The surface's chain skips the (expensive, per-contract) open-interest
        # merge, so OI is unknown here — gate on quotes and spread only. The
        # desk's own skew slices keep the full OI filter.
        points = skew_slice(chain, expiry=expiry, width_pct=0.10, min_open_interest=0)
        if len(points) < 6:
            continue
        slices.append(
            {
                "dte": dte,
                "points": [
                    {"strike": p.strike, "iv": p.iv, "moneyness": p.moneyness} for p in points
                ],
            }
        )

    # Cap at 30 curves, sampled evenly across the tenor range so the waterfall
    # keeps both its dense near end and its long tail.
    if len(slices) > 30:
        step = len(slices) / 30
        slices = [slices[int(i * step)] for i in range(30)]

    _SURFACE_CACHE[key] = (_time.monotonic(), slices)
    return {"symbol": key, "spot": chain.spot, "slices": slices, "cached": False}


@api.get("/decision/{decision_id}", summary="One decision, in full, for the trace view")
def get_decision(decision_id: str) -> Decision:
    """The complete record behind one audit entry — including the trace block
    (scan, measure, classify, build), every gate result, and the stress grid
    when one breached. This is what /trace/<id> renders.
    """
    decision = audit.by_id(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail=f"No decision {decision_id!r}.")
    return decision


@api.get("/refusal-exhibit", summary="The most recent refusal with a genuine breach")
def get_refusal_exhibit() -> dict[str, Any]:
    """A real refused candidate whose stress grid actually breached.

    This feeds the landing page's centrepiece. It is drawn from the audit
    history — an actual decision the desk made on real market data — and if no
    such refusal has been recorded yet, it says so rather than inventing one.
    """
    for decision in audit.recent(limit=200, action="REFUSED"):
        cells = decision.detail.get("stress_grid")
        if not cells:
            continue
        gates = decision.detail.get("gates") or []
        stress_reason = next(
            (g.get("reason") for g in gates if g.get("gate") == "stress" and not g.get("passed")),
            decision.reason,
        )
        return {
            "available": True,
            "ts": decision.ts.isoformat(),
            "symbol": decision.symbol,
            "kind": decision.detail.get("kind"),
            "structure_id": decision.structure_id,
            "max_loss": decision.detail.get("max_loss"),
            "reason": stress_reason,
            "cells": cells,
        }
    return {
        "available": False,
        "note": "No refusal with a stress breach has been recorded yet.",
    }


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
        # Two windows, deliberately separate. "cycle" is the most recent single
        # pass; "counts" aggregates every decision since the session began.
        # Mixing them produced a self-contradictory "0 survived · 1 filled".
        "cycle": {
            "ts": report.ts.isoformat() if report else None,
            "scanned": len(report.scanned) if report else 0,
            "candidates_built": len(report.candidates) if report else 0,
            "survivors": (sum(1 for c in report.candidates if c.passed_all) if report else 0),
        },
        "counts": counts,
        "counts_since": session_start.astimezone(UTC).isoformat(),
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
def health() -> dict[str, Any]:
    return get_health()
