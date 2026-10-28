"""Recovery rehearsal (counterfactual replay before approval) and rollback of failed actions."""
from datetime import timedelta

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.recovery.executors import ActionResult, MockExecutor
from tests.test_diagnostics import timeouts_for
from tests.test_incidents import AUTH, NOW, baseline, line, recent, run
from tests.test_recovery import ALICE, BOB, RC, approved_and_executed, env, feed, propose, s01_incident, verify, window  # noqa: F401


def contract(client, cid):
    return client.get(f"{RC}/{cid}", headers=AUTH).json()


# ---- rehearsal --------------------------------------------------------------------------------

def test_every_proposal_is_rehearsed_and_labelled_as_simulation(env):
    client, ex = env
    c = propose(client, s01_incident(client)).json()
    r = c["contract"]["rehearsal"]
    assert r["model_version"] == "rehearsal-v1" and "Simulation evidence" in r["label"]
    assert len(c["rehearsals"]) == 1 and c["rehearsals"][0]["requested_by"] == "rehearsal-engine"
    assert ex.calls == []  # a rehearsal never runs anything


def test_rollback_rehearsal_is_inconclusive_without_previous_release_traffic(env):
    """All recent traffic is on v2: nothing shows how v1 behaves now, so no optimistic guess."""
    client, _ = env
    r = propose(client, s01_incident(client)).json()["contract"]["rehearsal"]
    assert r["outcome"] == "inconclusive" and "previous release" in r["reason"]


def test_rollback_rehearsal_passes_when_the_old_release_is_healthy_in_the_same_window(env):
    client, _ = env
    new = recent(500, 1, version="v2", message="unhandled_exception", products=False)
    old = [e | {"request_id": e["request_id"] + "-old", "event_time": (NOW - timedelta(seconds=96 - i * 9)).isoformat()}
           for i, e in enumerate(recent(201, 20, version="v1", products=False))]
    [inc] = run(client, baseline() + new + old)
    c = propose(client, inc, action_template="rollback_release").json()
    assert c["contract"]["rehearsal"]["outcome"] == "pass", c["contract"]["rehearsal"]


def test_failed_rehearsal_blocks_approval_until_acknowledged(env):
    """P1 shape: the old release fails too, so rolling back cannot help."""
    client, ex = env
    bad = recent(500, 1, version="v2", message="unhandled_exception", products=False)
    also_old = [e | {"request_id": e["request_id"] + "-old"} for e in recent(500, 1, version="v1", message="unhandled_exception")]
    [inc] = run(client, baseline() + bad + also_old)
    c = propose(client, inc).json()
    assert c["action_template"] == "rollback_release" and c["contract"]["rehearsal"]["outcome"] == "fail"
    refused = client.post(f"{RC}/{c['id']}/approve", json={"decision": "approve"}, headers=BOB)
    assert refused.status_code == 409 and refused.json()["error"] == "rehearsal_failed"
    # rejecting needs no acknowledgement
    ok = client.post(f"{RC}/{c['id']}/approve", json={"decision": "reject", "comment": "replay says no"}, headers=BOB)
    assert ok.status_code == 200 and ok.json()["state"] == "REJECTED" and ex.calls == []


def test_acknowledged_rehearsal_failure_is_audited(env):
    client, _ = env
    [inc] = run(client, baseline() + recent(500, 40))
    c = propose(client, inc, action_template="rollback_release").json()
    res = client.post(f"{RC}/{c['id']}/approve", json={"decision": "approve", "acknowledge_rehearsal_failure": True}, headers=BOB)
    assert res.status_code == 200
    approval = next(t for t in contract(client, c["id"])["transitions"] if t["to"] == "READY_FOR_ACTION")
    assert approval["actor"] == "bob"
    assert approval["details"] == {"rehearsal_outcome": "fail", "acknowledged_rehearsal_failure": True}


def test_payment_rehearsal_passes_when_failures_match_timeouts(env):
    client, _ = env
    rec = recent(504, 3004)
    [inc] = run(client, baseline() + rec, timeouts_for(rec))
    r = propose(client, inc).json()["contract"]["rehearsal"]
    assert r["outcome"] == "pass", r


def test_payment_rehearsal_fails_when_timeouts_are_unrelated(env):
    """P2 shape: timeouts are logged, but by other requests. Restoring the provider changes nothing."""
    client, _ = env
    unrelated = [line(NOW - timedelta(seconds=90 - i * 9), "/api/checkout", 504, 3004, "v1", "payment_timeout") for i in range(10)]
    [inc] = run(client, baseline() + recent(504, 3004), unrelated)
    r = propose(client, inc, action_template="restore_payment_simulator").json()["contract"]["rehearsal"]
    assert r["outcome"] == "fail" and "no failing request is linked" in r["reason"]


def test_query_fix_rehearsal_needs_traces(env):
    client, _ = env
    [inc] = run(client, baseline() + recent(201, 1520))
    r = propose(client, inc, action_template="apply_query_fix").json()["contract"]["rehearsal"]
    assert r["outcome"] == "inconclusive" and "No affected request measures" in r["reason"]


def test_rehearsal_can_be_rerun_before_execution_only(env):
    client, _ = env
    inc = s01_incident(client)
    c = propose(client, inc).json()
    again = client.post(f"{RC}/{c['id']}/rehearse", headers=BOB)
    assert again.status_code == 200 and len(again.json()["rehearsals"]) == 2
    client.post(f"{RC}/{c['id']}/approve", json={"decision": "approve"}, headers=BOB)
    client.post(f"{RC}/{c['id']}/execute", headers=BOB)
    late = client.post(f"{RC}/{c['id']}/rehearse", headers=BOB)
    assert late.status_code == 409 and late.json()["error"] == "not_rehearsable"


def test_revert_actions_cannot_be_proposed_on_their_own(env):
    client, _ = env
    res = propose(client, s01_incident(client), action_template="revert_rollback_release")
    assert res.status_code == 400 and res.json()["error"] == "rollback_only_action"


# ---- rollback ---------------------------------------------------------------------------------

def test_pre_action_state_is_captured_before_the_action(env):
    client, _ = env
    done = approved_and_executed(client, s01_incident(client))
    snap = done["contract"]["pre_action_snapshot"]
    assert snap and snap["state"]["action"] == "rollback_release"


def test_guardrail_breach_recommends_rollback_and_rollback_restores_state(env):
    client, ex = env
    inc = s01_incident(client)
    done = approved_and_executed(client, inc)
    start, end = window(done)
    feed(client, start, checkout=(201, 20), products=(500, 5))
    v = verify(client, done["id"], end + timedelta(seconds=1)).json()
    assert v["outcome"] == "fail" and v["rollback_recommended"] is True
    rb = client.post(f"{RC}/{done['id']}/rollback", json={"reason": "products broke after the rollback"}, headers=ALICE)
    assert rb.status_code == 200, rb.text
    out = rb.json()
    assert out["state"] == "ROLLED_BACK" and out["outcome"] == "fail"  # undoing a change is not a recovery
    assert out["rollback_run"]["status"] == "succeeded" and out["rollback_run"]["requested_by"] == "alice"
    assert ex.calls == [("rollback_release", "demo"), ("revert:rollback_release", "demo")]
    assert [t["to"] for t in out["transitions"]][-3:] == ["FAILED", "ROLLING_BACK", "ROLLED_BACK"]
    assert client.get(f"/api/v1/incidents/{inc['id']}", headers=AUTH).json()["status"] == "open"


def test_unmet_success_condition_does_not_recommend_rollback_but_allows_it(env):
    client, _ = env
    done = approved_and_executed(client, s01_incident(client))
    start, end = window(done)
    feed(client, start, checkout=(500, 3))
    v = verify(client, done["id"], end + timedelta(seconds=1)).json()
    assert v["outcome"] == "fail" and v["rollback_recommended"] is False
    assert client.post(f"{RC}/{done['id']}/rollback", headers=BOB).json()["state"] == "ROLLED_BACK"


def test_inconclusive_contract_can_be_rolled_back(env):
    client, _ = env
    done = approved_and_executed(client, s01_incident(client))
    start, end = window(done)
    feed(client, start, offsets=[10, 40])
    assert verify(client, done["id"], end + timedelta(seconds=1)).json()["outcome"] == "inconclusive"
    assert client.post(f"{RC}/{done['id']}/rollback", headers=BOB).json()["state"] == "ROLLED_BACK"


def test_rollback_happens_at_most_once_and_never_on_success(env):
    client, ex = env
    done = approved_and_executed(client, s01_incident(client))
    start, end = window(done)
    feed(client, start, checkout=(500, 3))
    verify(client, done["id"], end + timedelta(seconds=1))
    assert client.post(f"{RC}/{done['id']}/rollback", headers=BOB).status_code == 200
    again = client.post(f"{RC}/{done['id']}/rollback", headers=BOB)
    assert again.status_code == 409 and again.json()["error"] == "not_rollbackable"
    assert sum(1 for c in ex.calls if c[0].startswith("revert:")) == 1


def test_succeeded_contract_cannot_be_rolled_back(env):
    client, _ = env
    done = approved_and_executed(client, s01_incident(client))
    start, end = window(done)
    feed(client, start)
    assert verify(client, done["id"], end + timedelta(seconds=1)).json()["outcome"] == "pass"
    res = client.post(f"{RC}/{done['id']}/rollback", headers=BOB)
    assert res.status_code == 409 and res.json()["error"] == "not_rollbackable"


def _client(tmp_path, executor):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 't.db'}", ingest_token="test-token", max_batch_events=2000)
    return TestClient(create_app(settings, executor=executor))


def test_failed_snapshot_means_the_action_is_never_attempted(tmp_path):
    class NoSnapshot(MockExecutor):
        def capture(self, *a):
            return ActionResult(False, {"error": "admin endpoint unreachable"})

    ex = NoSnapshot()
    client = _client(tmp_path, ex)
    c = propose(client, s01_incident(client)).json()
    client.post(f"{RC}/{c['id']}/approve", json={"decision": "approve"}, headers=BOB)
    done = client.post(f"{RC}/{c['id']}/execute", headers=BOB).json()
    assert done["state"] == "FAILED" and ex.calls == []
    assert done["action_run"]["output"]["error"] == "pre_action_snapshot_failed"
    # nothing changed, so there is nothing to roll back
    res = client.post(f"{RC}/{c['id']}/rollback", headers=BOB)
    assert res.status_code == 409 and res.json()["error"] == "nothing_to_roll_back"


def test_failed_revert_is_reported_for_manual_intervention(tmp_path):
    class BadRevert(MockExecutor):
        def revert(self, *a):
            return ActionResult(False, {"error": "timeout"})

    client = _client(tmp_path, BadRevert())
    done = approved_and_executed(client, s01_incident(client))
    start, end = window(done)
    feed(client, start, checkout=(500, 3))
    verify(client, done["id"], end + timedelta(seconds=1))
    out = client.post(f"{RC}/{done['id']}/rollback", headers=BOB).json()
    assert out["state"] == "ROLLBACK_FAILED" and out["rollback_run"]["status"] == "failed"
    assert "manual intervention" in out["transitions"][-1]["note"]


def test_a_rolled_back_incident_can_get_a_new_contract(env):
    client, _ = env
    inc = s01_incident(client)
    done = approved_and_executed(client, inc)
    start, end = window(done)
    feed(client, start, checkout=(500, 3))
    verify(client, done["id"], end + timedelta(seconds=1))
    client.post(f"{RC}/{done['id']}/rollback", headers=BOB)
    assert propose(client, inc).status_code == 201


def test_shop_executor_snapshot_and_revert(monkeypatch):
    """The shop executor reads the active scenario first and restores exactly that on revert."""
    import httpx

    from app.recovery.executors import ShopAdminExecutor
    seen = []

    class Res:
        def __init__(self, active):
            self.status_code, self._a = 200, active

        def json(self):
            return {"active": self._a}

    monkeypatch.setattr(httpx, "get", lambda url, **kw: Res("S01_bad_deployment"))
    monkeypatch.setattr(httpx, "post", lambda url, json, **kw: seen.append(json["scenario"]) or Res(json["scenario"]))
    ex = ShopAdminExecutor("https://shop.example", "secret")
    snap = ex.capture("rollback_release", "demo", 5)
    assert snap.ok and snap.output == {"scenario": "S01_bad_deployment"}
    assert ex.run("rollback_release", "demo", 5).ok
    assert ex.revert("rollback_release", "demo", snap.output, 5).ok
    assert seen == ["none", "S01_bad_deployment"]


def test_measured_zero_effect_fails_the_rehearsal(env):
    """S02 shape: queries are traced and fast, so a query fix would change nothing measurable."""
    from tests.test_new_scenarios import with_traces, traced_baseline
    from tests.test_diagnostics import ingest_spans
    client, _ = env
    events, spans = with_traces(recent(201, 1520), lambda e: [("db.pool.acquire", 1300, 1), ("db.query orders.lookup", 6, 1)],
                                start_index=500)
    base, base_spans = traced_baseline()
    ingest_spans(client, base_spans + spans)
    [inc] = run(client, base + events)
    r = propose(client, inc, action_template="apply_query_fix").json()["contract"]["rehearsal"]
    assert r["outcome"] == "fail" and "no effect" in r["reason"]
    r = propose_after_reject(client, inc, "recycle_db_pool")
    assert r["outcome"] == "pass", r


def propose_after_reject(client, inc, action):
    for c in client.get(f"{RC}?incident_id={inc['id']}", headers=AUTH).json():
        if c["state"] == "AWAITING_APPROVAL":
            client.post(f"{RC}/{c['id']}/approve", json={"decision": "reject"}, headers=BOB)
    return propose(client, inc, action_template=action).json()["contract"]["rehearsal"]
