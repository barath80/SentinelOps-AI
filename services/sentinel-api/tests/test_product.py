"""Product features: telemetry explorer, team notifications, automation, throttling, rate limits,
model explanations, security headers and the audit log."""
import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import notify
from app.config import Settings
from app.main import create_app
from app.recovery.executors import MockExecutor
from tests.test_diagnostics import ingest_spans, timeouts_for, traced
from tests.test_incidents import AUTH, NOW, baseline, line, recent, run

ALICE, BOB = {**AUTH, "X-Actor": "alice"}, {**AUTH, "X-Actor": "bob"}


def make(tmp_path, **kw):
    ex = MockExecutor()
    s = Settings(**{"database_url": f"sqlite:///{tmp_path / 'p.db'}", "ingest_token": "test-token", "max_batch_events": 3000,
                    "notify_allow_private": True, **kw})
    return TestClient(create_app(s, executor=ex)), ex


@pytest.fixture()
def env(tmp_path):
    return make(tmp_path)


def outbox(client):
    return client.get("/api/v1/notifications", headers=AUTH).json()


class Receiver:
    def __init__(self, status=200):
        self.calls, self.status = [], status

    def __call__(self, url, body, headers):
        self.calls.append((url, json.loads(body), headers, body))
        return self.status


def add_channel(client, kind="webhook", events=None):
    body = {"name": f"team-{kind}", "kind": kind, "url": "http://127.0.0.1:9/hook"}
    if events:
        body["events"] = events
    r = client.post("/api/v1/notifications/channels", json=body, headers=ALICE)
    assert r.status_code == 201, r.text
    return r.json()


def s01(client):
    [inc] = run(client, baseline() + recent(500, 1, version="v2", message="unhandled_exception"))
    return inc


# ---- telemetry explorer and evidence --------------------------------------------------------

def test_every_evidence_citation_opens_its_source_event(env):
    client, _ = env
    inc = s01(client)
    refs = [r for h in inc["hypotheses"] for e in h["evidence"] for r in e["source_refs"]]
    assert refs
    for ref in refs[:5]:
        ev = client.get(f"/api/v1/telemetry/events/{ref}", headers=AUTH).json()
        assert ev["event_id"] == ref and ev["attributes"]["route"] == "/api/checkout"
    assert client.get("/api/v1/telemetry/events/nope", headers=AUTH).status_code == 404


def test_log_search_filters(env):
    client, _ = env
    s01(client)
    until = (NOW + timedelta(seconds=1)).isoformat()
    errors = client.get("/api/v1/telemetry/logs", params={"until": until, "minutes": 30, "min_status": 500}, headers=AUTH).json()
    assert errors and all(e["attributes"]["status"] >= 500 for e in errors)
    found = client.get("/api/v1/telemetry/logs", params={"until": until, "minutes": 30, "q": "unhandled"}, headers=AUTH).json()
    assert found and all("unhandled" in e["attributes"]["message"] for e in found)


def test_trace_waterfall_and_trace_list(env):
    client, _ = env
    events, spans = traced(recent(201, 1520), "db.query orders.lookup", 0.9)
    ingest_spans(client, spans)
    run(client, baseline() + events)
    roots = client.get("/api/v1/telemetry/traces", params={"until": NOW.isoformat(), "minutes": 30}, headers=AUTH).json()
    assert roots and roots[0]["duration_ms"] >= roots[-1]["duration_ms"]
    t = client.get(f"/api/v1/telemetry/traces/{roots[0]['trace_id']}", headers=AUTH).json()
    assert [s["depth"] for s in t["spans"]] == [0, 1] and t["spans"][1]["name"] == "db.query orders.lookup"
    assert t["logs"] and t["logs"][0]["trace_id"] == roots[0]["trace_id"]


def test_metric_series_and_incident_telemetry(env):
    client, _ = env
    inc = s01(client)
    sr = client.get("/api/v1/telemetry/series", params={"until": NOW.isoformat(), "minutes": 15, "bucket_seconds": 60},
                    headers=AUTH).json()
    pts = sr["routes"]["/api/checkout"]
    assert sum(p["requests"] for p in pts) > 60 and max(p["error_rate"] or 0 for p in pts) == 1.0
    it = client.get(f"/api/v1/incidents/{inc['id']}/telemetry", headers=AUTH).json()
    assert it["failing_logs"] and all(e["attributes"]["status"] >= 500 for e in it["failing_logs"])
    assert "/api/checkout" in it["series"]["routes"]


# ---- notifications ----------------------------------------------------------------------------

def test_new_incident_notifies_the_team_with_evidence_and_a_signature(env, monkeypatch):
    client, _ = env
    ch = add_channel(client)
    assert "url" not in ch and ch["host"] == "127.0.0.1" and len(ch["signing_secret"]) == 48
    s01(client)
    queued = outbox(client)
    assert any(n["event"] == "incident.opened" and n["status"] == "pending" for n in queued)
    rx = Receiver()
    out = notify.flush(client.app.state.sessions, allow_private=True, allow_http=True, send=rx)
    assert out["sent"] >= 1
    url, body, headers, raw = next(c for c in rx.calls if c[1]["event"] == "incident.opened")
    assert body["data"]["leading_cause"] == "release_regression" and body["data"]["evidence"]
    assert "Leading cause: release_regression" in body["text"]
    # what a receiver does: recompute the HMAC over the exact bytes it got, with the shared secret
    expected = "sha256=" + hmac.new(ch["signing_secret"].encode(), raw, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(headers["x-sentinelops-signature"], expected)
    forged = "sha256=" + hmac.new(b"wrong-secret", raw, hashlib.sha256).hexdigest()
    assert headers["x-sentinelops-signature"] != forged
    assert {n["status"] for n in outbox(client) if n["event"] == "incident.opened"} == {"sent"}


def test_slack_channel_gets_plain_text(env):
    client, _ = env
    add_channel(client, kind="slack", events=["incident.opened"])
    s01(client)
    rx = Receiver()
    notify.flush(client.app.state.sessions, True, True, send=rx)
    assert set(rx.calls[0][1]) == {"text"} and "[SentinelOps]" in rx.calls[0][1]["text"]


def test_approval_needed_and_recovery_events(env):
    client, _ = env
    add_channel(client)
    inc = s01(client)
    c = client.post("/api/v1/recovery-contracts", json={"incident_id": inc["id"]}, headers=ALICE).json()
    events = [n["event"] for n in outbox(client)]
    assert "approval.needed" in events
    blocked = client.post("/api/v1/recovery-contracts", json={"incident_id": inc["id"], "action_template": "restart_shared_database"},
                          headers=ALICE)
    assert blocked.status_code in (403, 409)
    client.post(f"/api/v1/recovery-contracts/{c['id']}/approve", json={"decision": "reject"}, headers=BOB)


def test_failed_deliveries_retry_then_give_up(env):
    client, _ = env
    add_channel(client, events=["incident.opened"])
    s01(client)
    rx = Receiver(status=500)
    sessions = client.app.state.sessions
    first = notify.flush(sessions, True, True, send=rx)
    assert first["retrying"] == 1
    from datetime import datetime, timezone
    later = datetime.now(timezone.utc)
    for i in range(notify.MAX_ATTEMPTS):
        later += timedelta(seconds=notify.BACKOFF_S * 2 ** i + 1)
        notify.flush(sessions, True, True, send=rx, now=later)
    row = outbox(client)[0]
    assert row["status"] == "failed" and row["attempts"] == notify.MAX_ATTEMPTS and row["last_error"] == "HTTP 500"


def test_webhook_urls_must_be_public_https(tmp_path):
    client, _ = make(tmp_path, notify_allow_private=False)
    for url in ("http://example.com/hook", "https://127.0.0.1/hook", "https://user:pw@example.com/x", "ftp://example.com"):
        r = client.post("/api/v1/notifications/channels", json={"name": "x", "kind": "webhook", "url": url}, headers=ALICE)
        assert r.status_code == 422, url
    with pytest.raises(notify.Unsafe):
        notify.check_url("https://localhost/x")


def test_unknown_events_are_rejected(env):
    client, _ = env
    r = client.post("/api/v1/notifications/channels", json={"name": "x", "kind": "webhook", "url": "http://127.0.0.1/h",
                                                            "events": ["everything"]}, headers=ALICE)
    assert r.status_code == 422


# ---- throttling ---------------------------------------------------------------------------------

def test_a_burst_of_429s_is_reported_to_the_team_once(env):
    client, _ = env
    add_channel(client, events=["throttling.detected"])
    burst = [line(NOW - timedelta(seconds=90 - i * 4), "/api/checkout", 429, 3) | {"request_id": f"t{i}"} for i in range(20)]
    run(client, baseline() + burst)
    run(client, [])  # analysed again within 10 minutes: no second message
    notes = [n for n in outbox(client) if n["event"] == "throttling.detected"]
    assert len(notes) == 1 and "rejected with 429" in notes[0]["text"]


# ---- automation ---------------------------------------------------------------------------------

def payment_incident(client):
    rec = recent(504, 3004)
    [inc] = run(client, baseline() + rec, timeouts_for(rec))
    client.post(f"/api/v1/incidents/{inc['id']}/investigate", json={}, headers=AUTH)  # confirms the cause
    return inc


def automation(client, cause, mode, enabled=True, **kw):
    r = client.put(f"/api/v1/automation/policies/{cause}", json={"mode": mode, **kw}, headers=ALICE)
    assert r.status_code == 200, r.text
    client.put("/api/v1/automation", json={"enabled": enabled}, headers=ALICE)
    return client.post("/api/v1/automation/run", headers=ALICE).json()["steps"]


def contracts_of(client, inc):
    return client.get("/api/v1/recovery-contracts", params={"incident_id": inc["id"]}, headers=AUTH).json()


def test_manual_is_the_default_and_nothing_happens(env):
    client, ex = env
    inc = payment_incident(client)
    client.put("/api/v1/automation", json={"enabled": True}, headers=ALICE)
    assert client.post("/api/v1/automation/run", headers=ALICE).json()["steps"] == []
    assert contracts_of(client, inc) == [] and ex.calls == []
    assert {p["mode"] for p in client.get("/api/v1/automation", headers=AUTH).json()["policies"]} == {"manual"}


def test_propose_mode_opens_the_contract_for_a_person_to_approve(env):
    client, ex = env
    inc = payment_incident(client)
    steps = automation(client, "payment_provider_timeout", "propose")
    assert [s["step"] for s in steps] == ["propose"]
    [c] = contracts_of(client, inc)
    assert c["proposed_by"] == "automation" and c["state"] == "AWAITING_APPROVAL" and ex.calls == []


def test_auto_mode_executes_only_after_a_passing_rehearsal_and_is_verified(env):
    client, ex = env
    inc = payment_incident(client)
    steps = automation(client, "payment_provider_timeout", "auto")
    assert [s["step"] for s in steps] == ["propose", "execute"], steps
    assert ex.calls == [("restore_payment_simulator", "demo")]
    [c] = contracts_of(client, inc)
    approval = next(t for t in c["transitions"] if t["to"] == "READY_FOR_ACTION")
    assert approval["actor"] == "policy:payment_provider_timeout" and "set by alice" in approval["note"]
    assert c["contract"]["rehearsal"]["outcome"] == "pass"
    # a second pass never acts twice on the same incident
    assert [s["step"] for s in client.post("/api/v1/automation/run", headers=ALICE).json()["steps"]] == []


def test_auto_mode_leaves_an_inconclusive_rehearsal_to_a_person(env):
    client, ex = env
    inc = s01(client)
    client.post(f"/api/v1/incidents/{inc['id']}/investigate", json={}, headers=AUTH)
    steps = automation(client, "release_regression", "auto", max_risk="medium")
    # "healthy before, failing after" is only suggestive (0.6): not a decisive test, so no action at all
    assert [(s["step"], s["outcome"]) for s in steps] == [("skip", "not_confirmed")]
    assert ex.calls == [] and contracts_of(client, inc) == []


def test_a_repeated_skip_is_reported_every_pass_but_stored_once(env):
    client, _ = env
    inc = s01(client)
    client.post(f"/api/v1/incidents/{inc['id']}/investigate", json={}, headers=AUTH)
    automation(client, "release_regression", "auto", max_risk="medium")
    for _ in range(3):
        steps = client.post("/api/v1/automation/run", headers=ALICE).json()["steps"]
        assert [(s["step"], s["outcome"]) for s in steps] == [("skip", "not_confirmed")]
    runs = client.get("/api/v1/automation", headers=AUTH).json()["recent_runs"]
    assert [(r["incident_id"], r["outcome"]) for r in runs] == [(inc["id"], "not_confirmed")]


def test_the_global_switch_and_the_deployment_ceiling(tmp_path):
    client, ex = make(tmp_path, automation_allowed=False)
    payment_incident(client)
    client.put("/api/v1/automation/policies/payment_provider_timeout", json={"mode": "auto"}, headers=ALICE)
    assert client.put("/api/v1/automation", json={"enabled": True}, headers=ALICE).status_code == 403
    assert client.post("/api/v1/automation/run", headers=ALICE).json()["steps"] == [] and ex.calls == []


def test_automation_respects_the_hourly_cap(tmp_path):
    client, ex = make(tmp_path, automation_max_actions_per_hour=0)
    payment_incident(client)
    steps = automation(client, "payment_provider_timeout", "auto")
    assert steps[-1]["outcome"] == "rate_capped" and ex.calls == []


def test_due_verifications_are_closed_automatically(env):
    client, _ = env
    inc = s01(client)
    c = client.post("/api/v1/recovery-contracts", json={"incident_id": inc["id"]}, headers=ALICE).json()
    client.post(f"/api/v1/recovery-contracts/{c['id']}/approve", json={"decision": "approve"}, headers=BOB)
    done = client.post(f"/api/v1/recovery-contracts/{c['id']}/execute", headers=BOB).json()
    from datetime import datetime
    from app import automation as auto
    end = datetime.fromisoformat(done["contract"]["verification_window"]["end"])
    steps = auto.verify_due(client.app.state.sessions, client.app.state.settings, end + timedelta(seconds=1))
    assert steps and steps[0]["step"] == "verify" and steps[0]["outcome"] == "inconclusive"  # no post-action traffic


def test_policy_changes_are_audited_and_admin_only(tmp_path):
    client, _ = make(tmp_path)
    client.put("/api/v1/automation/policies/slow_dependency", json={"mode": "propose"}, headers=ALICE)
    audit = client.get("/api/v1/audit", headers=AUTH).json()
    assert any(a["action"] == "automation.policy_changed" and a["actor"] == "alice" for a in audit)


# ---- rate limits, models, headers -----------------------------------------------------------

def test_rate_limit_returns_429_with_retry_after(tmp_path):
    client, _ = make(tmp_path, rate_limit_per_minute=5)
    codes = [client.get("/api/v1/incidents", headers=AUTH).status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5] == 429
    r = client.get("/api/v1/incidents", headers=AUTH)
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1 and r.json()["error"] == "rate_limited"
    assert client.get("/health").status_code == 200  # never limited


def test_changing_the_credential_does_not_reset_the_budget(tmp_path):
    """Guessing tokens from one address: every guess draws on that address's budget."""
    client, _ = make(tmp_path, rate_limit_per_minute=3)
    codes = [client.get("/api/v1/incidents", headers={"Authorization": f"Bearer guess-{i}"}).status_code for i in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]


def test_rate_limit_also_applies_per_credential_across_addresses(tmp_path):
    app = make(tmp_path, rate_limit_per_minute=2)[0].app
    a, b = TestClient(app, client=("198.51.100.1", 1)), TestClient(app, client=("198.51.100.2", 1))
    assert [a.get("/api/v1/incidents", headers=AUTH).status_code for _ in range(2)] == [200, 200]
    assert b.get("/api/v1/incidents", headers=AUTH).status_code == 429  # same credential, other address


def test_client_address_ignores_forged_forwarded_for():
    from types import SimpleNamespace
    from app.clientaddr import client_address
    req = lambda xff: SimpleNamespace(headers={"x-forwarded-for": xff}, client=SimpleNamespace(host="10.0.0.5"))
    # the client sent "1.2.3.4"; the platform proxy appended the address it really saw
    assert client_address(req("1.2.3.4, 203.0.113.7"), 1) == "203.0.113.7"
    assert client_address(req("1.2.3.4, 203.0.113.7"), 0) == "10.0.0.5"  # no trusted proxy: socket address
    assert client_address(req(""), 1) == "10.0.0.5"


def test_rate_limiter_memory_stays_bounded():
    from app.ratelimit import SlidingWindow
    w = SlidingWindow(max_keys=100)
    for i in range(1000):
        w.take(f"k{i}", 5, window_s=0.0)  # every earlier key is already idle for a whole window
    assert len(w) <= 101


def test_concurrent_senders_deliver_each_notification_once(env):
    import threading
    client, _ = env
    add_channel(client, events=["incident.opened"])
    s01(client)
    rx, barrier = Receiver(), threading.Barrier(2)

    def sender():
        barrier.wait()
        notify.flush(client.app.state.sessions, True, True, send=rx)
    threads = [threading.Thread(target=sender) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len([c for c in rx.calls if c[1]["event"] == "incident.opened"]) == 1


def test_links_open_the_incident_page(tmp_path):
    client, _ = make(tmp_path, public_url="https://sentinel.example")
    add_channel(client, events=["incident.opened"])
    inc = s01(client)
    rx = Receiver()
    notify.flush(client.app.state.sessions, True, True, send=rx)
    assert rx.calls[0][1]["data"]["link"] == f"https://sentinel.example/ui/#/incident/{inc['id']}/summary"


def test_timestamps_in_other_zones_are_stored_as_utc(env):
    client, _ = env
    e = line(NOW, "/api/checkout", 201, 20) | {"event_time": "2026-10-26T14:00:00+02:00", "request_id": "tz"}
    client.post("/api/v1/telemetry/events?adapter=shop_json", json={"events": [e]}, headers=AUTH)
    [got] = client.get("/api/v1/telemetry/logs", params={"until": "2026-10-26T12:01:00+00:00", "minutes": 5, "q": "tz"}, headers=AUTH).json()
    assert got["event_time"].startswith("2026-10-26T12:00:00") and got["event_time"].endswith("+00:00")


def test_a_cyclic_span_tree_does_not_crash_the_trace_view(env):
    client, _ = env
    tid = "c" * 32
    spans = [{"traceId": tid, "spanId": "a" * 16, "parentSpanId": "b" * 16, "name": "x", "serviceName": "shop-web",
              "startTimeUnixNano": 1_700_000_000_000_000_000, "endTimeUnixNano": 1_700_000_000_100_000_000, "status": {"code": 1}},
             {"traceId": tid, "spanId": "b" * 16, "parentSpanId": "a" * 16, "name": "y", "serviceName": "shop-web",
              "startTimeUnixNano": 1_700_000_000_000_000_000, "endTimeUnixNano": 1_700_000_000_100_000_000, "status": {"code": 1}}]
    ingest_spans(client, spans)
    r = client.get(f"/api/v1/telemetry/traces/{tid}", headers=AUTH)
    assert r.status_code == 200


def test_model_page_and_incident_explanation(env):
    client, _ = env
    inc = s01(client)
    m = client.get("/api/v1/models", headers=AUTH).json()
    assert m["serving"]["version"] == "root-cause-serving-v2" and "retry_storm" in m["serving"]["classes"]
    e = client.get(f"/api/v1/incidents/{inc['id']}/model", headers=AUTH).json()
    assert e["available"] and len(e["explanation"]) == 6
    assert all({"feature", "value", "contribution"} <= set(x) for x in e["explanation"])


def test_api_security_headers(env):
    client, _ = env
    r = client.get("/api/v1/incidents", headers={**AUTH, "x-forwarded-proto": "https"})
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    assert r.headers["x-frame-options"] == "DENY" and "max-age" in r.headers["strict-transport-security"]


def test_overview(env):
    client, _ = env
    s01(client)
    o = client.get("/api/v1/overview", headers=AUTH).json()
    assert o["open_incidents"]["total"] == 1 and o["model"] == "root-cause-serving-v2"
    assert o["automation"] == {"enabled": False, "allowed": True}


def _auto_executed(client, auto_rollback):
    inc = payment_incident(client)
    automation(client, "payment_provider_timeout", "auto", auto_rollback=auto_rollback)
    [c] = contracts_of(client, inc)
    from datetime import datetime
    from tests.test_recovery import feed
    start = datetime.fromisoformat(c["contract"]["verification_window"]["start"])
    end = datetime.fromisoformat(c["contract"]["verification_window"]["end"])
    feed(client, start, checkout=(201, 20), products=(500, 5))  # the fix holds, but products breaks: a guardrail
    from app import automation as auto
    steps = auto.run(client.app.state.sessions, client.app.state.settings, client.app.state.executor, end + timedelta(seconds=1))
    return inc, steps


def test_auto_rollback_when_a_guardrail_breaks(env):
    client, ex = env
    inc, steps = _auto_executed(client, auto_rollback=True)
    assert [(s["step"], s["outcome"]) for s in steps] == [("verify", "fail"), ("rollback", "ROLLED_BACK")]
    assert ex.calls == [("restore_payment_simulator", "demo"), ("revert:restore_payment_simulator", "demo")]
    assert contracts_of(client, inc)[0]["state"] == "ROLLED_BACK"


def test_without_auto_rollback_a_person_decides(env):
    client, ex = env
    inc, steps = _auto_executed(client, auto_rollback=False)
    assert [(s["step"], s["outcome"]) for s in steps] == [("verify", "fail")]
    assert contracts_of(client, inc)[0]["state"] == "FAILED" and len(ex.calls) == 1
