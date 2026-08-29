"""The API surface.

Two things matter here beyond "does it return JSON":

* **No secret ever leaves this service.** The frontend holds no credential, so
  every response is checked for anything resembling one.
* **The kill switch is authenticated.** It is the only write endpoint, and an
  unauthenticated one on a public demo URL would be an obvious hole.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from skew.api import app
from skew.audit import log as audit
from skew.config import settings


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_kill_switch():
    original = settings.kill_switch
    yield
    settings.kill_switch = original


# ------------------------------------------------------------------ read


def test_status_states_the_paper_only_guarantee(client):
    body = client.get("/api/status").json()
    assert body["ok"] is True
    assert body["paper_only"] is True
    assert "paper" in body["base_url"]
    assert body["version"]


def test_root_and_health(client):
    assert client.get("/").json()["paper_only"] is True
    assert client.get("/health").json() == {"status": "ok"}


def test_read_endpoints_return_empty_collections_before_a_cycle(client):
    for path in ("/api/universe", "/api/candidates", "/api/audit"):
        response = client.get(path)
        assert response.status_code == 200
        assert isinstance(response.json(), list)


def test_unknown_symbol_and_candidate_404(client):
    assert client.get("/api/universe/ZZZZ").status_code == 404
    assert client.get("/api/stress/no-such-candidate").status_code == 404


def test_audit_returns_decisions_newest_first(client):
    audit.record(action="ABSTAINED", reason="first", risk_tier=0, symbol="SPY")
    audit.record(action="REFUSED", reason="second", risk_tier=0, symbol="QQQ")

    body = client.get("/api/audit?limit=10").json()
    assert len(body) == 2
    assert body[0]["reason"] == "second"
    assert body[0]["action"] == "REFUSED"


def test_audit_filters_by_action(client):
    audit.record(action="ABSTAINED", reason="a", risk_tier=0)
    audit.record(action="REFUSED", reason="b", risk_tier=0)
    body = client.get("/api/audit?action=REFUSED").json()
    assert [d["action"] for d in body] == ["REFUSED"]


def test_audit_rejects_an_invalid_action_filter(client):
    assert client.get("/api/audit?action=DELETE_EVERYTHING").status_code == 422


def test_audit_counts_report_the_ratio(client):
    """A desk that refused forty times and traded twice is doing its job."""
    audit.record(action="REFUSED", reason="a", risk_tier=0)
    audit.record(action="REFUSED", reason="b", risk_tier=0)
    audit.record(action="EXECUTED", reason="c", risk_tier=0)

    counts = client.get("/api/audit/counts").json()
    assert counts["REFUSED"] == 2
    assert counts["EXECUTED"] == 1
    assert counts["TOTAL"] == 3


def test_iv_history_labels_its_own_window(client):
    """A short self-collected window must never be presented as a 52-week one."""
    from skew.data.store import record_iv

    record_iv("SPY", atm_iv=0.15)
    body = client.get("/api/iv-history/SPY").json()

    assert body["symbol"] == "SPY"
    assert body["observations"] == 1
    assert "window_days" in body
    assert "Alpaca serves no historical implied" in body["note"]


# ------------------------------------------------------------------ kill switch


def test_kill_switch_requires_a_token(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "s3cret")
    monkeypatch.setattr(settings, "operator_token", "")
    assert client.post("/api/kill").status_code == 401
    assert client.post("/api/kill", headers={"x-admin-token": "wrong"}).status_code == 401


def test_kill_switch_engages_with_the_right_token(client, monkeypatch):
    # The singleton read the real .env at import; clear operator_token so the
    # legacy-alias path under test is actually the one exercised.
    monkeypatch.setattr(settings, "operator_token", "")
    monkeypatch.setattr(settings, "admin_token", "s3cret")

    response = client.post("/api/kill", headers={"x-admin-token": "s3cret"})
    assert response.status_code == 200
    assert response.json()["kill_switch"] is True
    assert settings.kill_switch is True

    released = client.post("/api/kill?engage=false", headers={"x-admin-token": "s3cret"})
    assert released.json()["kill_switch"] is False


def test_engaging_the_kill_switch_is_audited(client, monkeypatch):
    # The singleton read the real .env at import; clear operator_token so the
    # legacy-alias path under test is actually the one exercised.
    monkeypatch.setattr(settings, "operator_token", "")
    monkeypatch.setattr(settings, "admin_token", "s3cret")
    client.post("/api/kill", headers={"x-admin-token": "s3cret"})

    entries = client.get("/api/audit?limit=5").json()
    assert any("Kill switch ENGAGED" in d["reason"] for d in entries)


def test_kill_switch_refuses_when_no_token_is_configured(client, monkeypatch):
    """Better to fail closed than to expose an unauthenticated write endpoint."""
    monkeypatch.setattr(settings, "admin_token", "")
    monkeypatch.setattr(settings, "operator_token", "")
    response = client.post("/api/kill", headers={"x-admin-token": "anything"})
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_every_write_endpoint_requires_the_operator_token(client, monkeypatch):
    """The action surface is exactly three endpoints, all token-gated.

    Asserted against the OpenAPI schema rather than app.routes, because that is
    the actual documented public surface — and because this FastAPI version
    nests included routers, so walking app.routes would silently pass by
    finding nothing at all.
    """
    paths = client.get("/openapi.json").json()["paths"]
    writes = sorted(
        (path, method.upper())
        for path, methods in paths.items()
        for method in methods
        if method.lower() not in ("get", "head", "options")
    )
    assert writes == [("/api/cycle", "POST"), ("/api/kill", "POST"), ("/api/universe", "POST")]

    # And every one of them 401s without the token, 503s when none configured.
    monkeypatch.setattr(settings, "operator_token", "op-secret")
    monkeypatch.setattr(settings, "admin_token", "")
    for path, query in (
        ("/api/cycle", ""),
        ("/api/kill", ""),
        ("/api/universe", "?symbol=SPY&action=add"),
    ):
        assert client.post(path + query).status_code == 401, path
        assert (
            client.post(path + query, headers={"x-operator-token": "wrong"}).status_code == 401
        ), path

    monkeypatch.setattr(settings, "operator_token", "")
    for path, query in (
        ("/api/cycle", ""),
        ("/api/kill", ""),
        ("/api/universe", "?symbol=SPY&action=add"),
    ):
        assert client.post(path + query).status_code == 503, path


def test_every_documented_endpoint_is_reachable(client):
    """Guards against the router-nesting trap above: if inclusion ever breaks,
    the schema goes empty and this fails rather than passing vacuously."""
    paths = client.get("/openapi.json").json()["paths"]
    assert len(paths) >= 8
    for expected in (
        "/api/status",
        "/api/universe",
        "/api/candidates",
        "/api/risk",
        "/api/audit",
        "/api/positions",
        "/api/kill",
    ):
        assert expected in paths


# ------------------------------------------------------------------ secrets


def test_no_endpoint_leaks_a_credential(client):
    """The frontend holds no key, and nothing here would give it one."""
    from skew.data.store import record_iv

    record_iv("SPY", atm_iv=0.15)
    audit.record(action="REFUSED", reason="x", risk_tier=0, symbol="SPY")

    needles = [
        v
        for v in (
            settings.alpaca_api_key,
            settings.alpaca_api_secret,
            settings.anthropic_api_key,
            settings.admin_token,
            settings.alpaca_account_number,
        )
        if v
    ]

    for path in (
        "/",
        "/api/status",
        "/api/universe",
        "/api/candidates",
        "/api/risk",
        "/api/audit",
        "/api/audit/counts",
        "/api/iv-history/SPY",
        "/openapi.json",
    ):
        body = client.get(path).text
        for needle in needles:
            assert needle not in body, f"{path} leaked a credential"
        lowered = body.lower()
        assert "api_secret" not in lowered
        assert "secret_key" not in lowered


def test_openapi_schema_documents_the_paper_only_claim(client):
    schema = client.get("/openapi.json").json()
    assert "paper trading only" in schema["info"]["description"].lower()


def test_vrp_history_labels_its_window_honestly(client):
    from skew.data.store import record_iv

    record_iv("SPY", atm_iv=0.15)
    body = client.get("/api/vrp-history/SPY").json()
    assert body["symbol"] == "SPY"
    assert body["observations"] == 1
    assert "window_days" in body
    assert "exactly as long as it says it is" in body["note"]
    assert isinstance(body["series"], list)
    # Broker is unavailable in unit tests, so the realized side may be None —
    # the endpoint must degrade rather than 500.
    for row in body["series"]:
        assert set(row) == {"date", "iv", "rv"}


# ------------------------------------------------------------------ operator


def test_universe_edits_persist_and_validate(client, monkeypatch):
    monkeypatch.setattr(settings, "operator_token", "op-secret")
    auth = {"x-operator-token": "op-secret"}

    body = client.post("/api/universe?symbol=xom&action=add", headers=auth).json()
    assert "XOM" in body["universe"]
    assert body["effective"] == "next cycle"

    # Persisted: a fresh read of the effective universe includes it.
    from skew.universe import effective_universe

    assert "XOM" in effective_universe(settings)

    body = client.post("/api/universe?symbol=XOM&action=remove", headers=auth).json()
    assert "XOM" not in body["universe"]

    # Garbage is refused with a reason, not stored. (Anything longer than 8
    # chars is cut off even earlier by the query-parameter schema.)
    response = client.post("/api/universe?symbol=1BAD&action=add", headers=auth)
    assert response.status_code == 422
    assert "plausible ticker" in response.json()["detail"]


def test_universe_cannot_be_emptied(client, monkeypatch):
    monkeypatch.setattr(settings, "operator_token", "op-secret")
    monkeypatch.setattr(settings, "universe", "SPY")
    auth = {"x-operator-token": "op-secret"}
    response = client.post("/api/universe?symbol=SPY&action=remove", headers=auth)
    assert response.status_code == 422
    assert "cannot be emptied" in response.json()["detail"]


def test_risk_tier_has_no_write_endpoint(client):
    """The earned-authority story: risk limits are strictly read-only. There is
    no route that can set a tier, a budget, or a gate threshold."""
    paths = client.get("/openapi.json").json()["paths"]
    for path, methods in paths.items():
        if "risk" in path or "tier" in path or "budget" in path:
            assert set(methods) <= {"get"}, f"{path} must be read-only"


def test_cycle_status_is_public_and_shaped(client):
    body = client.get("/api/cycle/status").json()
    assert set(body) == {"progress", "last_cycle"}
    assert body["progress"]["running"] is False
    assert "phase" in body["progress"]


def test_session_summary_is_public_and_names_the_session(client):
    from skew.audit import log as audit_log

    audit_log.record(
        action="EXECUTED",
        reason="Submitted a thing.",
        risk_tier=0,
        symbol="AAPL",
        order_id="skew-test-1",
    )
    body = client.get("/api/session").json()
    assert body["session_date"]
    assert body["counts"]["EXECUTED"] >= 1
    assert body["last_fill"]["symbol"] == "AAPL"
    assert body["last_fill"]["order_id"] == "skew-test-1"


def test_status_names_the_last_session(client):
    body = client.get("/api/status").json()
    assert "last_session" in body
    # ISO date, and never a weekend/holiday.
    import datetime

    day = datetime.date.fromisoformat(body["last_session"])
    from skew.data.calendar import is_trading_day

    assert is_trading_day(day)
