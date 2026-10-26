from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import maintenance
from app.config import Settings
from app.db import EventRow, IncidentRow, make_session_factory
from app.main import create_app
from tests.test_incidents import AUTH, NOW, baseline, line, recent, run


def make(tmp_path, **kw):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 't.db'}", ingest_token="test-token", max_batch_events=2000, **kw)
    return settings, TestClient(create_app(settings))


def event_count(settings):
    sessions = make_session_factory(settings.database_url)
    with sessions() as s:
        return s.scalar(select(func.count()).select_from(EventRow))


def test_tick_analyzes_without_being_asked(tmp_path):
    settings, client = make(tmp_path)
    r = client.post("/api/v1/telemetry/events?adapter=shop_json", headers=AUTH,
                    json={"events": baseline() + recent(500, 1, version="v2", message="unhandled_exception")})
    assert r.json()["rejected"] == 0
    sessions = make_session_factory(settings.database_url)
    out = maintenance.tick(sessions, settings, NOW)
    assert out["analyzed"] == 1 and out["investigated"] == 0 and out["purged"] is None
    assert len(client.get("/api/v1/incidents", headers=AUTH).json()) == 1


def test_auto_investigate_is_read_only_and_runs_once(tmp_path):
    settings, client = make(tmp_path, auto_investigate=True)
    client.post("/api/v1/telemetry/events?adapter=shop_json", headers=AUTH,
                json={"events": baseline() + recent(500, 1, version="v2", message="unhandled_exception")})
    sessions = make_session_factory(settings.database_url)
    first = maintenance.tick(sessions, settings, NOW)
    second = maintenance.tick(sessions, settings, NOW)
    assert first["investigated"] == 1 and second["investigated"] == 0
    inc = client.get("/api/v1/incidents", headers=AUTH).json()[0]
    assert inc["diagnostic_runs"] and inc["status"] == "open"
    # the scheduler never creates, approves or executes a recovery contract
    assert client.get(f"/api/v1/recovery-contracts?incident_id={inc['id']}", headers=AUTH).json() == []


def test_purge_removes_old_events_but_keeps_cited_evidence(tmp_path):
    settings, client = make(tmp_path)
    old = [line(NOW - timedelta(days=30, seconds=i), "/api/products", 200, 9) | {"request_id": f"old{i}"} for i in range(40)]
    client.post("/api/v1/telemetry/events?adapter=shop_json", headers=AUTH, json={"events": old})
    [inc] = run(client, baseline() + recent(500, 1, version="v2", message="unhandled_exception"))
    cited = {r for h in inc["hypotheses"] for e in h["evidence"] for r in e["source_refs"]}
    assert cited
    before = event_count(settings)

    sessions = make_session_factory(settings.database_url)
    with sessions.begin() as s:
        result = maintenance.purge_events(s, settings.default_tenant_id, NOW + timedelta(days=1))  # everything is "old"
    assert result["deleted"] > 0 and result["kept_because_cited"] == len(cited)
    with sessions() as s:
        remaining = set(s.scalars(select(EventRow.event_id)))
    assert remaining == cited, "only cited events survive"
    assert event_count(settings) == len(cited) < before
    # evidence still resolves after the purge
    again = client.get(f"/api/v1/incidents/{inc['id']}", headers=AUTH).json()
    assert {r for h in again["hypotheses"] for e in h["evidence"] for r in e["source_refs"]} == cited


def test_purge_only_touches_events_older_than_the_cutoff(tmp_path):
    settings, client = make(tmp_path)
    events = [line(NOW - timedelta(days=d), "/api/products", 200, 9) | {"request_id": f"d{d}"} for d in (1, 2, 10, 20)]
    client.post("/api/v1/telemetry/events?adapter=shop_json", headers=AUTH, json={"events": events})
    sessions = make_session_factory(settings.database_url)
    with sessions.begin() as s:
        r = maintenance.purge_events(s, settings.default_tenant_id, NOW - timedelta(days=7))
    assert r["deleted"] == 2 and event_count(settings) == 2


def test_purge_endpoint_requires_auth_and_reports(tmp_path):
    settings, client = make(tmp_path, retention_days=7)
    assert client.post("/api/v1/maintenance/purge").status_code == 401
    ok = client.post("/api/v1/maintenance/purge?days=7", headers=AUTH)
    assert ok.status_code == 200 and ok.json()["deleted"] == 0
    assert client.post("/api/v1/maintenance/purge?days=0", headers=AUTH).status_code == 200  # 0 = use the configured default


def test_scheduler_loop_survives_a_failed_pass(tmp_path, monkeypatch):
    import asyncio
    settings, _ = make(tmp_path, analyze_interval_seconds=1)
    sessions = make_session_factory(settings.database_url)
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return {"analyzed": 0}

    monkeypatch.setattr(maintenance, "tick", flaky)

    async def go():
        t = asyncio.create_task(maintenance.run_forever(sessions, settings, interval=0.05))
        await asyncio.sleep(0.4)
        t.cancel()

    asyncio.run(go())
    assert calls["n"] >= 2, "the loop must keep running after an exception"
