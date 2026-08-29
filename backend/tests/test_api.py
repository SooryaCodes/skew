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
    assert client.post("/api/kill").status_code == 401
    assert client.post("/api/kill", headers={"x-admin-token": "wrong"}).status_code == 401


def test_kill_switch_engages_with_the_right_token(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "s3cret")

    response = client.post("/api/kill", headers={"x-admin-token": "s3cret"})
    assert response.status_code == 200
    assert response.json()["kill_switch"] is True
    assert settings.kill_switch is True

    released = client.post("/api/kill?engage=false", headers={"x-admin-token": "s3cret"})
    assert released.json()["kill_switch"] is False


def test_engaging_the_kill_switch_is_audited(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "s3cret")
    client.post("/api/kill", headers={"x-admin-token": "s3cret"})

    entries = client.get("/api/audit?limit=5").json()
    assert any("Kill switch ENGAGED" in d["reason"] for d in entries)


def test_kill_switch_refuses_when_no_token_is_configured(client, monkeypatch):
    """Better to fail closed than to expose an unauthenticated write endpoint."""
    monkeypatch.setattr(settings, "admin_token", "")
    response = client.post("/api/kill", headers={"x-admin-token": "anything"})
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_the_only_write_endpoint_is_the_kill_switch(client):
    """Every other route is read-only.

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
    assert writes == [("/api/kill", "POST")]


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
