import json
import os
import subprocess
import sys
from datetime import timedelta

from app.prevention import check_json_rule, check_markdown, check_python
from tests.test_incidents import AUTH, baseline, client, line, recent, run  # noqa: F401
from tests.test_recovery import ALICE, BOB, RC, approved_and_executed, env, feed, propose, s01_incident, verify, window  # noqa: F401


def resolve(client, inc):
    done = approved_and_executed(client, inc)
    start, end = window(done)
    feed(client, start)
    assert verify(client, done["id"], end + timedelta(seconds=1)).json()["outcome"] == "pass"
    return done


def generate(client, inc, headers=ALICE):
    return client.post(f"/api/v1/incidents/{inc['id']}/prevention", headers=headers)


def test_cause_must_be_confirmed_first(env):
    client, _ = env
    inc = s01_incident(client)
    res = generate(client, inc)
    assert res.status_code == 409 and res.json()["error"] == "cause_not_confirmed"
    propose(client, inc)  # a contract exists but nothing was verified
    assert generate(client, inc).status_code == 409


def test_artifacts_are_generated_linked_and_checked(env):
    client, _ = env
    inc = s01_incident(client)
    done = resolve(client, inc)
    res = generate(client, inc)
    assert res.status_code == 200
    arts = res.json()
    kinds = [a["type"] for a in arts]
    assert kinds[:3] == ["regression_test", "alert_rule", "runbook_amendment"] and "monitoring_gap" in kinds
    assert all(a["review_status"] == "proposed" and a["checks_passed"] for a in arts)
    assert all(a["contract_id"] == done["id"] and a["incident_id"] == inc["id"] for a in arts)

    full = client.get(f"/api/v1/incidents/{inc['id']}", headers=AUTH).json()
    ledger = {e["id"] for h in full["hypotheses"] for e in h["evidence"]}
    assert arts[0]["evidence_ids"] and set(arts[0]["evidence_ids"]) <= ledger  # every link resolves
    stored = {e["event_id"] for e in client.get("/api/v1/telemetry/events?limit=200", headers=AUTH).json()}
    assert arts[0]["source_event_ids"] and set(arts[0]["source_event_ids"]) <= stored
    assert inc["id"] in arts[0]["content"] and done["id"] in arts[0]["content"]

    again = generate(client, inc).json()  # idempotent
    assert [a["id"] for a in again] == [a["id"] for a in arts]
    assert len(client.get(f"/api/v1/incidents/{inc['id']}/prevention", headers=AUTH).json()) == len(arts)


def test_generated_regression_test_is_valid_pytest_and_skips_without_a_shop(env, tmp_path):
    client, _ = env
    inc = s01_incident(client)
    resolve(client, inc)
    code = next(a for a in generate(client, inc).json() if a["type"] == "regression_test")["content"]
    f = tmp_path / "test_generated.py"
    f.write_text(code, encoding="utf-8")
    out = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(f)],
                         capture_output=True, text=True, env={k: v for k, v in os.environ.items() if k != "SHOP_URL"})
    assert "1 skipped" in out.stdout, out.stdout + out.stderr


def test_alert_rule_is_valid_json_with_the_evidence_attached(env):
    client, _ = env
    inc = s01_incident(client)
    resolve(client, inc)
    rule = json.loads(next(a for a in generate(client, inc).json() if a["type"] == "alert_rule")["content"])
    assert rule["condition"]["sli"] == "error_rate" and rule["status"] == "proposed: not deployed"
    assert rule["motivated_by"]["cause"] == "release_regression" and rule["motivated_by"]["evidence_ids"]


def test_slow_dependency_artifacts_use_the_contract_slo_target(env):
    client, _ = env
    [inc] = run(client, baseline() + recent(201, 1520))
    c = propose(client, inc).json()
    assert c["action_template"] == "apply_query_fix"
    client.post(f"{RC}/{c['id']}/approve", json={"decision": "approve"}, headers=BOB)
    done = client.post(f"{RC}/{c['id']}/execute", headers=BOB).json()
    start, end = window(done)
    feed(client, start)
    assert verify(client, c["id"], end + timedelta(seconds=1)).json()["outcome"] == "pass"
    arts = generate(client, inc).json()
    target = c["contract"]["slo_basis"]["/api/checkout"]["p95_target_ms"]
    test = next(a for a in arts if a["type"] == "regression_test")["content"]
    rule = json.loads(next(a for a in arts if a["type"] == "alert_rule")["content"])
    assert f"p95 <= {target}" in test.replace("p95 {p95:.0f} ms exceeds", "") or f"<= {target}" in test
    assert rule["condition"]["threshold"] == target and rule["condition"]["sli"] == "p95_latency_ms"
    gaps = [a for a in arts if a["type"] == "monitoring_gap"]
    assert any("database" in g["content"].lower() for g in gaps), "the missing-evidence item becomes a follow-up"


def test_an_unbacked_action_does_not_confirm_a_cause(env):
    """Rolling back on an inconclusive incident can 'pass' verification, but proves no cause."""
    client, _ = env
    [inc] = run(client, baseline() + recent(500, 40))
    c = propose(client, inc, action_template="rollback_release").json()
    # every failing request is on the old release already, so the rehearsal predicts the rollback fails
    assert c["contract"]["rehearsal"]["outcome"] == "fail"
    client.post(f"{RC}/{c['id']}/approve", json={"decision": "approve", "acknowledge_rehearsal_failure": True}, headers=BOB)
    done = client.post(f"{RC}/{c['id']}/execute", headers=BOB).json()
    start, end = window(done)
    feed(client, start)
    assert verify(client, c["id"], end + timedelta(seconds=1)).json()["outcome"] == "pass"
    res = generate(client, inc)
    assert res.status_code == 409 and res.json()["error"] == "cause_not_confirmed"


def test_review_flow(env):
    client, _ = env
    inc = s01_incident(client)
    resolve(client, inc)
    arts = generate(client, inc).json()
    a, b = arts[0], arts[1]
    ok = client.post(f"/api/v1/prevention-artifacts/{a['id']}/review", json={"decision": "approve", "comment": "reads fine"}, headers=BOB)
    assert ok.status_code == 200 and ok.json()["review_status"] == "approved" and ok.json()["reviewed_by"] == "bob"
    assert client.post(f"/api/v1/prevention-artifacts/{a['id']}/review", json={"decision": "reject"}, headers=BOB).status_code == 409
    rej = client.post(f"/api/v1/prevention-artifacts/{b['id']}/review", json={"decision": "reject"}, headers=BOB)
    assert rej.json()["review_status"] == "rejected"
    assert client.post(f"/api/v1/prevention-artifacts/{a['id']}/review", json={"decision": "approve"}, headers=AUTH).status_code == 400
    assert client.post("/api/v1/prevention-artifacts/nope/review", json={"decision": "approve"}, headers=BOB).status_code == 404
    assert client.post(f"/api/v1/incidents/{inc['id']}/prevention").status_code == 401


# ---- the static checks themselves -------------------------------------------------------------------

def failed(checks):
    return {c["name"] for c in checks if not c["passed"]}


def test_check_python_rejects_dangerous_or_malformed_code():
    ok = 'import os\nimport pytest\nSHOP_URL = os.environ.get("SHOP_URL")\n'
    assert failed(check_python(ok)) == set()
    assert "imports_allow_listed" in failed(check_python("import subprocess\n" + ok))
    assert "imports_allow_listed" in failed(check_python("from shutil import rmtree\n" + ok))
    assert "no_dynamic_code_or_file_access" in failed(check_python(ok + 'os.system("rm -rf /")\n'))
    assert "no_dynamic_code_or_file_access" in failed(check_python(ok + 'eval("1")\n'))
    assert "no_dynamic_code_or_file_access" in failed(check_python(ok + 'open("/etc/passwd")\n'))
    assert "no_secrets" in failed(check_python(ok + 'KEY = "postgresql://u:pw@host/db"\n'))
    assert "parses" in failed(check_python("def broken(:\n"))
    assert "targets_env_var_not_production" in failed(check_python('import os\nURL = "https://shop.example.com"\n'))


def test_check_json_and_markdown():
    assert failed(check_json_rule("{not json")) == {"valid_json"}
    assert "has_required_fields" in failed(check_json_rule('{"name": "x"}'))
    assert failed(check_markdown("Evidence: abc")) == set()
    assert "has_evidence_links" in failed(check_markdown("no links here"))
    assert "no_secrets" in failed(check_markdown("Evidence: Bearer abcdefghijklmnopqrstuv"))
