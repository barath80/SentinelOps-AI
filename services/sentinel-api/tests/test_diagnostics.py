from datetime import timedelta

import pytest

from tests.test_incidents import AUTH, NOW, baseline, client, line, recent, run  # noqa: F401


def timeouts_for(events, route="/api/checkout", version="v1", only_bad=True):
    """payment_timeout events sharing the request ids of the failing checkout requests."""
    return [
        line(e_time(e), route, 504, 3004, version, "payment_timeout", ) | {"request_id": e["request_id"]}
        for e in events if e["route"] == route and e["status"] >= 500
    ]


def e_time(e):
    from datetime import datetime
    return datetime.fromisoformat(e["event_time"]) + timedelta(milliseconds=50)


def investigate(client, incident_id, budget=3):
    res = client.post(f"/api/v1/incidents/{incident_id}/investigate", json={"budget": budget}, headers=AUTH)
    assert res.status_code == 200, res.text
    return res.json()


def hyp(inc, key):
    return next(h for h in inc["hypotheses"] if h["cause_key"] == key)


def test_s01_leader_survives_its_own_falsification_test(client):
    [inc] = run(client, baseline() + recent(500, 1, version="v2", message="unhandled_exception"))
    out = investigate(client, inc["id"])
    rep = out["report"]
    assert rep["stop_reason"] == "leader_survived_falsification" and not rep["leader_changed"]
    assert [s["test_id"] for s in rep["steps"]] == ["compare_error_rate_before_after_release"]
    assert rep["steps"][0]["outcome"] == "supports"
    release = hyp(out["incident"], "release_regression")
    assert any(e["created_by"] == "diagnostic:compare_error_rate_before_after_release" for e in release["evidence"])
    assert release["score_history"], "the earlier score must be preserved"
    assert out["incident"]["diagnostic_runs"][0]["outcome"] == "supports"


def test_leader_is_overturned_when_old_release_fails_too(client):
    """Release label changed, but v1 fails just as much as v2: the release is not the cause."""
    bad = recent(500, 1, version="v2", message="unhandled_exception", products=False)
    also_old = recent(500, 1, version="v1", message="unhandled_exception", products=True)
    for i, e in enumerate(also_old):  # shift so request ids differ
        e["request_id"] += "-old"
    [inc] = run(client, baseline() + bad + also_old)
    assert inc["hypotheses"][0]["cause_key"] == "release_regression"  # before testing, it leads
    out = investigate(client, inc["id"])
    release = hyp(out["incident"], "release_regression")
    assert release["status"] == "falsified"
    assert out["incident"]["assessment"] == "inconclusive"  # abstains instead of picking another cause
    assert out["report"]["leader_changed"] is True


def test_payment_leader_survives_when_timeouts_match_failures(client):
    recent_events = recent(504, 3004)
    [inc] = run(client, baseline() + recent_events, timeouts_for(recent_events))
    out = investigate(client, inc["id"])
    assert out["report"]["stop_reason"] == "leader_survived_falsification"
    assert out["report"]["steps"][0]["test_id"] == "inspect_payment_provider_status_and_spans"
    assert out["incident"]["hypotheses"][0]["cause_key"] == "payment_provider_timeout"


def test_payment_leader_falsified_when_timeouts_do_not_match_failing_requests(client):
    recent_events = recent(504, 3004)
    unrelated = [line(NOW - timedelta(seconds=90 - i * 9), "/api/checkout", 504, 3004, "v1", "payment_timeout") for i in range(10)]
    [inc] = run(client, baseline() + recent_events, unrelated)
    assert inc["hypotheses"][0]["cause_key"] == "payment_provider_timeout"
    out = investigate(client, inc["id"])
    assert hyp(out["incident"], "payment_provider_timeout")["status"] == "falsified"


def test_untestable_leader_is_reported_not_confirmed(client):
    """S03: the slow-dependency leader needs DB metrics that do not exist."""
    [inc] = run(client, baseline() + recent(201, 1520))
    out = investigate(client, inc["id"])
    assert out["report"]["stop_reason"] == "leader_untestable_missing_data"
    run_ = next(r for r in out["incident"]["diagnostic_runs"] if r["test_id"] == "inspect_db_pool_wait_and_query_duration")
    assert run_["outcome"] == "no_data"
    slow = hyp(out["incident"], "slow_dependency")
    assert slow["status"] != "falsified"
    # no evidence was fabricated by the no-data test
    assert not any(e["created_by"].startswith("diagnostic:") for e in slow["evidence"])


def test_db_metrics_make_the_slow_dependency_testable(client):
    metrics = []
    for i in range(20):
        t = NOW - timedelta(seconds=500 - i * 25)
        slow = i >= 18
        metrics.append({
            "event_id": f"00000000-0000-4000-8000-{i:012d}", "environment": "demo", "service_name": "postgres",
            "event_type": "metric", "event_time": t.isoformat(), "source_ref": "prom:db",
            "attributes": {"metric_name": "db_query_duration_ms", "value": 900 if slow else 12},
        })
    # make the last points land inside the recent window
    for m in metrics[-4:]:
        m["event_time"] = (NOW - timedelta(seconds=60)).isoformat()
    r = client.post("/api/v1/telemetry/events?adapter=normalized", json={"events": metrics}, headers=AUTH)
    assert r.json()["accepted"] == 20
    [inc] = run(client, baseline() + recent(201, 1520))
    out = investigate(client, inc["id"])
    assert out["report"]["stop_reason"] == "leader_survived_falsification"
    assert out["report"]["steps"][0]["outcome"] == "supports"


def test_unknown_or_malicious_test_id_is_rejected(client):
    [inc] = run(client, baseline() + recent(500, 1, version="v2", message="unhandled_exception"))
    for bad in ("rm -rf /", "DROP TABLE events", "../../etc/passwd", ""):
        res = client.post(f"/api/v1/incidents/{inc['id']}/diagnostics", json={"test_id": bad}, headers=AUTH)
        assert res.status_code == 400


def test_running_a_test_twice_is_idempotent(client):
    [inc] = run(client, baseline() + recent(500, 1, version="v2", message="unhandled_exception"))
    url = f"/api/v1/incidents/{inc['id']}/diagnostics"
    body = {"test_id": "compare_error_rate_before_after_release"}
    first = client.post(url, json=body, headers=AUTH).json()
    second = client.post(url, json=body, headers=AUTH).json()
    assert len(second["diagnostic_runs"]) == 1
    n = lambda i: sum(e["created_by"].startswith("diagnostic:") for e in hyp(i, "release_regression")["evidence"])
    assert n(first) == n(second) == 1
    assert hyp(first, "release_regression")["score"] == hyp(second, "release_regression")["score"]


def test_reanalysis_keeps_diagnostics_and_history(client):
    [inc] = run(client, baseline() + recent(500, 1, version="v2", message="unhandled_exception"))
    investigate(client, inc["id"])
    again = client.post("/api/v1/incidents/analyze", params={"as_of": NOW.isoformat()}, headers=AUTH).json()
    assert [i["id"] for i in again] == [inc["id"]]
    release = hyp(again[0], "release_regression")
    assert len(again[0]["diagnostic_runs"]) == 1
    assert any(e["created_by"].startswith("diagnostic:") for e in release["evidence"])
    assert release["score_history"]


def test_diagnostic_endpoints_require_auth_and_404(client):
    assert client.post("/api/v1/incidents/x/investigate").status_code == 401
    assert client.post("/api/v1/incidents/nope/investigate", json={}, headers=AUTH).status_code == 404
    assert client.post("/api/v1/incidents/nope/diagnostics", json={"test_id": "compare_request_rate_to_baseline"}, headers=AUTH).status_code == 404
