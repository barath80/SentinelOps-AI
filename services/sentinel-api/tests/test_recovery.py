from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.recovery.executors import ActionResult, MockExecutor
from tests.test_incidents import AUTH, baseline, line, recent, run

ALICE = {**AUTH, "X-Actor": "alice"}
BOB = {**AUTH, "X-Actor": "bob"}
RC = "/api/v1/recovery-contracts"


@pytest.fixture()
def env(tmp_path):
    ex = MockExecutor()
    settings = Settings(database_url=f"sqlite:///{tmp_path / 't.db'}", ingest_token="test-token", max_batch_events=2000)
    return TestClient(create_app(settings, executor=ex)), ex


def s01_incident(client):
    [inc] = run(client, baseline() + recent(500, 1, version="v2", message="unhandled_exception"))
    return inc


def propose(client, inc, **body):
    return client.post(RC, json={"incident_id": inc["id"], **body}, headers=ALICE)


def approved_and_executed(client, inc):
    c = propose(client, inc).json()
    assert client.post(f"{RC}/{c['id']}/approve", json={"decision": "approve", "comment": "ok"}, headers=BOB).status_code == 200
    done = client.post(f"{RC}/{c['id']}/execute", headers=BOB)
    assert done.status_code == 200, done.text
    return done.json()


def window(contract):
    w = contract["contract"]["verification_window"]
    return datetime.fromisoformat(w["start"]), datetime.fromisoformat(w["end"])


def feed(client, start, checkout=(201, 20), products=(200, 9), n=25, offsets=None, tag="v"):
    """Ingest post-action traffic evenly across the verification window."""
    offs = offsets if offsets is not None else [2 + i * 2.2 for i in range(n)]
    events = []
    for i, o in enumerate(offs):
        t = start + timedelta(seconds=o)
        events.append(line(t, "/api/checkout", checkout[0], checkout[1]) | {"request_id": f"{tag}-c{i}"})
        events.append(line(t, "/api/products", products[0], products[1]) | {"request_id": f"{tag}-p{i}"})
    r = client.post("/api/v1/telemetry/events?adapter=shop_json", json={"events": events}, headers=AUTH)
    assert r.json()["rejected"] == 0, r.text


def verify(client, cid, at):
    return client.post(f"{RC}/{cid}/verify", params={"as_of": at.isoformat()}, headers=BOB)


# ---- the happy path and the audit trail -----------------------------------------------------

def test_full_flow_pass_and_audit_trail(env):
    client, ex = env
    inc = s01_incident(client)
    c = propose(client, inc)
    assert c.status_code == 201
    c = c.json()
    assert c["state"] == "AWAITING_APPROVAL" and c["action_template"] == "rollback_release"
    assert c["contract"]["basis"]["score_is_probability"] is False
    assert c["contract"]["policy"]["blast_radius"]["risk_label"] in {"low", "medium"}
    client.post(f"{RC}/{c['id']}/approve", json={"decision": "approve"}, headers=BOB)
    ex_res = client.post(f"{RC}/{c['id']}/execute", headers=BOB).json()
    assert ex_res["state"] == "VERIFYING" and ex_res["outcome"] == "pending"
    assert ex.calls == [("rollback_release", "demo")]
    start, end = window(ex_res)
    feed(client, start)
    v = verify(client, c["id"], end + timedelta(seconds=1)).json()
    assert v["outcome"] == "pass" and v["state"] == "SUCCEEDED" and v["final"] is True
    final = client.get(f"{RC}/{c['id']}", headers=AUTH).json()
    assert [t["to"] for t in final["transitions"]] == [
        "VALIDATED", "AWAITING_APPROVAL", "READY_FOR_ACTION", "EXECUTING", "VERIFYING", "SUCCEEDED"]
    assert {t["policy_version"] for t in final["transitions"]} == {"policy-v1"}
    assert [a["reviewer"] for a in final["approvals"]] == ["bob"]
    vals = {p["description"]: p["value"] for p in final["verifications"][0]["predicates"]}
    assert vals["error_rate(/api/checkout) <= 0.01"] == 0.0
    assert client.get(f"/api/v1/incidents/{inc['id']}", headers=AUTH).json()["status"] == "resolved"


def test_executed_action_is_not_a_recovery(env):
    """The action ran fine, but the shop is still failing: the contract must say FAILED."""
    client, ex = env
    inc = s01_incident(client)
    done = approved_and_executed(client, inc)
    assert done["action_run"]["status"] == "succeeded"
    start, end = window(done)
    feed(client, start, checkout=(500, 3))
    v = verify(client, done["id"], end + timedelta(seconds=1)).json()
    assert v["outcome"] == "fail" and v["state"] == "FAILED"
    assert "success condition not met" in v["reason"]
    assert client.get(f"/api/v1/incidents/{inc['id']}", headers=AUTH).json()["status"] == "open"


def test_verification_is_pending_until_window_completes(env):
    client, _ = env
    done = approved_and_executed(client, s01_incident(client))
    start, end = window(done)
    feed(client, start)
    early = verify(client, done["id"], start + timedelta(seconds=20)).json()
    assert early["outcome"] == "pending" and early["final"] is False
    assert client.get(f"{RC}/{done['id']}", headers=AUTH).json()["state"] == "VERIFYING"


def test_too_few_samples_is_inconclusive_not_pass(env):
    client, _ = env
    done = approved_and_executed(client, s01_incident(client))
    start, end = window(done)
    feed(client, start, offsets=[10, 40])
    v = verify(client, done["id"], end + timedelta(seconds=1)).json()
    assert v["outcome"] == "inconclusive" and "insufficient_samples" in v["reason"]


def test_telemetry_gap_is_inconclusive(env):
    client, _ = env
    done = approved_and_executed(client, s01_incident(client))
    start, end = window(done)
    feed(client, start, offsets=[1, 2, 3, 4, 5, 6])  # then silence for 54 s
    v = verify(client, done["id"], end + timedelta(seconds=1)).json()
    assert v["outcome"] == "inconclusive" and "telemetry_gap" in v["reason"]


def test_guardrail_breach_fails_even_when_the_target_recovered(env):
    client, _ = env
    done = approved_and_executed(client, s01_incident(client))
    start, end = window(done)
    feed(client, start, checkout=(201, 20), products=(500, 5))
    v = verify(client, done["id"], end + timedelta(seconds=1)).json()
    assert v["outcome"] == "fail" and "guardrail breached" in v["reason"]


def test_final_verdict_is_idempotent(env):
    client, _ = env
    done = approved_and_executed(client, s01_incident(client))
    start, end = window(done)
    feed(client, start)
    first = verify(client, done["id"], end + timedelta(seconds=1)).json()
    again = verify(client, done["id"], end + timedelta(seconds=300)).json()
    assert first["outcome"] == again["outcome"] == "pass" and again["final"] is True
    assert len(client.get(f"{RC}/{done['id']}", headers=AUTH).json()["verifications"]) == 1


# ---- policy, approval and execution guards --------------------------------------------------

def test_unsafe_action_is_blocked_and_audited(env):
    client, ex = env
    inc = s01_incident(client)
    res = propose(client, inc, action_template="restart_shared_database")
    assert res.status_code == 403 and res.json()["error"] == "blocked_by_policy"
    assert any("environment_not_permitted" in r for r in res.json()["reasons"])
    assert any("blast_radius" in r for r in res.json()["reasons"])
    blocked = client.get(f"{RC}/{res.json()['contract_id']}", headers=AUTH).json()
    assert blocked["state"] == "BLOCKED" and [t["to"] for t in blocked["transitions"]] == ["VALIDATED", "BLOCKED"]
    for step in ("approve", "execute"):  # a blocked contract can never proceed
        r = client.post(f"{RC}/{blocked['id']}/{step}", json={"decision": "approve"}, headers=BOB)
        assert r.status_code == 409
    assert ex.calls == []


def test_unknown_action_is_denied_and_bad_names_are_rejected(env):
    client, ex = env
    inc = s01_incident(client)
    assert propose(client, inc, action_template="format_disk").status_code == 403
    assert propose(client, inc, action_template="rm -rf /").status_code == 422
    assert ex.calls == []


def test_production_environment_is_not_permitted(env):
    client, _ = env
    res = propose(client, s01_incident(client), environment="production")
    assert res.status_code == 403 and any("environment_not_permitted" in r for r in res.json()["reasons"])


def test_proposer_cannot_approve_their_own_contract(env):
    client, _ = env
    c = propose(client, s01_incident(client)).json()
    res = client.post(f"{RC}/{c['id']}/approve", json={"decision": "approve"}, headers=ALICE)
    assert res.status_code == 403 and res.json()["error"] == "four_eyes_required"


def test_cannot_execute_without_approval(env):
    client, ex = env
    c = propose(client, s01_incident(client)).json()
    res = client.post(f"{RC}/{c['id']}/execute", headers=BOB)
    assert res.status_code == 409 and ex.calls == []


def test_rejected_contract_cannot_run(env):
    client, ex = env
    c = propose(client, s01_incident(client)).json()
    client.post(f"{RC}/{c['id']}/approve", json={"decision": "reject", "comment": "not now"}, headers=BOB)
    assert client.get(f"{RC}/{c['id']}", headers=AUTH).json()["state"] == "REJECTED"
    assert client.post(f"{RC}/{c['id']}/execute", headers=BOB).status_code == 409 and ex.calls == []


def test_action_runs_at_most_once(env):
    client, ex = env
    c = propose(client, s01_incident(client)).json()
    client.post(f"{RC}/{c['id']}/approve", json={"decision": "approve"}, headers=BOB)
    assert client.post(f"{RC}/{c['id']}/execute", headers=BOB).status_code == 200
    assert client.post(f"{RC}/{c['id']}/execute", headers=BOB).status_code == 409
    assert len(ex.calls) == 1


def test_failed_action_never_reaches_verification(tmp_path):
    class Broken(MockExecutor):
        def run(self, *a):
            return ActionResult(False, {"error": "boom"})

    settings = Settings(database_url=f"sqlite:///{tmp_path / 't.db'}", ingest_token="test-token", max_batch_events=2000)
    client = TestClient(create_app(settings, executor=Broken()))
    inc = s01_incident(client)
    c = propose(client, inc).json()
    client.post(f"{RC}/{c['id']}/approve", json={"decision": "approve"}, headers=BOB)
    done = client.post(f"{RC}/{c['id']}/execute", headers=BOB).json()
    assert done["state"] == "FAILED" and done["outcome"] == "fail" and done["action_run"]["status"] == "failed"
    assert done["verifications"] == []


def test_inconclusive_incident_gets_no_automatic_recommendation(env):
    client, _ = env
    [inc] = run(client, baseline() + recent(500, 40))  # ambiguous: engine abstains
    assert inc["assessment"] == "inconclusive"
    res = propose(client, inc)
    assert res.status_code == 409 and res.json()["error"] == "incident_inconclusive_no_recommended_action"
    forced = propose(client, inc, action_template="rollback_release")
    assert forced.status_code == 201
    assert any("not backed by a leading diagnosis" in w for w in forced.json()["contract"]["warnings"])


def test_one_active_contract_per_incident(env):
    client, _ = env
    inc = s01_incident(client)
    assert propose(client, inc).status_code == 201
    assert propose(client, inc).status_code == 409


def test_headers_and_auth(env):
    client, _ = env
    inc = s01_incident(client)
    assert client.post(RC, json={"incident_id": inc["id"]}, headers=AUTH).status_code == 400  # no X-Actor
    assert client.post(RC, json={"incident_id": inc["id"]}).status_code == 401
    assert client.post(RC, json={"incident_id": "nope"}, headers=ALICE).status_code == 404
    assert client.get(f"{RC}/nope", headers=AUTH).status_code == 404


def test_action_catalogue_lists_the_blocked_action(env):
    client, _ = env
    cat = client.get("/api/v1/recovery-actions", headers=AUTH).json()
    db = next(a for a in cat["actions"] if a["id"] == "restart_shared_database")
    assert db["environments"] == [] and db["disruptive"] is True


def test_latency_target_is_anchored_to_the_baseline(env):
    """Where healthy checkouts already take ~600 ms, a fixed 500 ms target would be unreachable."""
    from tests.test_incidents import NOW
    client, _ = env
    slow_base = []
    for i in range(60):
        t = NOW - timedelta(seconds=600 - i * 7)
        slow_base.append(line(t, "/api/checkout", 201, 580 + (i % 5) * 4))
        slow_base.append(line(t + timedelta(seconds=1), "/api/products", 200, 9))
    [inc] = run(client, slow_base + recent(500, 1, version="v2", message="unhandled_exception"))
    c = propose(client, inc).json()
    basis = c["contract"]["slo_basis"]["/api/checkout"]
    assert basis["baseline_p95_ms"] >= 580 and basis["p95_target_ms"] == round(1.5 * basis["baseline_p95_ms"])
    p95 = next(p for p in c["contract"]["success_conditions"] if p["sli"] == "p95_latency_ms")
    assert p95["threshold"] == basis["p95_target_ms"] > 500


def test_latency_target_never_drops_below_the_blueprint_floor(env):
    client, _ = env
    c = propose(client, s01_incident(client)).json()
    assert c["contract"]["slo_basis"]["/api/checkout"]["p95_target_ms"] == 500


def test_p95_needs_enough_samples_to_be_judged(env):
    """12 healthy requests are not enough to call a p95 'met': the verdict must be inconclusive."""
    client, _ = env
    done = approved_and_executed(client, s01_incident(client))
    start, end = window(done)
    feed(client, start, n=12, offsets=[2 + i * 4.5 for i in range(12)])
    v = verify(client, done["id"], end + timedelta(seconds=1)).json()
    assert v["outcome"] == "inconclusive" and "insufficient_samples: 12 < 20" in v["reason"]
