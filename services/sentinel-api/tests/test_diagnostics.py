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


def test_s01_leader_stands_after_its_test_and_the_alternatives(client):
    [inc] = run(client, baseline() + recent(500, 1, version="v2", message="unhandled_exception"))
    out = investigate(client, inc["id"])
    rep = out["report"]
    # "healthy before, failing after" is only suggestive (0.6), so the alternatives are tested too
    assert rep["stop_reason"] == "leader_stands_alternatives_ruled_out" and not rep["leader_changed"]
    assert rep["steps"][0]["test_id"] == "compare_error_rate_before_after_release"
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


# ---- traces as evidence ------------------------------------------------------------------------

def traced(events, child_name, child_share, status_code=0):
    """Give each recent checkout line a trace id plus a root span and one child span."""
    from datetime import datetime as dt
    spans = []
    for i, e in enumerate(events):
        if e["route"] != "/api/checkout" or e["status"] < 200:
            continue
        tid = f"{i:032x}"
        e["trace_id"] = tid
        start = int(dt.fromisoformat(e["event_time"]).timestamp() * 1e9)
        dur = int(e["duration_ms"] * 1e6)
        spans.append({"traceId": tid, "spanId": f"{i:016x}", "name": "POST /api/checkout", "serviceName": "shop-web",
                      "startTimeUnixNano": start, "endTimeUnixNano": start + dur, "status": {"code": status_code}})
        spans.append({"traceId": tid, "spanId": f"{i + 1:015x}f", "parentSpanId": f"{i:016x}", "name": child_name,
                      "serviceName": "shop-web", "startTimeUnixNano": start, "endTimeUnixNano": start + int(dur * child_share),
                      "status": {"code": status_code}})
    return events, spans


def ingest_spans(client, spans):
    r = client.post("/api/v1/telemetry/events?adapter=otel_span", json={"events": spans}, headers=AUTH)
    assert r.json()["rejected"] == 0, r.text


def test_traces_make_the_slow_dependency_testable(client):
    events, spans = traced(recent(201, 1520), "db.query orders.lookup", 0.9)
    ingest_spans(client, spans)
    [inc] = run(client, baseline() + events)
    out = investigate(client, inc["id"])
    assert out["report"]["stop_reason"] == "leader_survived_falsification"
    run_ = next(r for r in out["incident"]["diagnostic_runs"] if r["test_id"] == "inspect_db_pool_wait_and_query_duration")
    assert run_["outcome"] == "supports" and run_["details"]["median_share_in_db_spans"] >= 0.8


def test_traces_can_overturn_the_slow_dependency(client):
    events, spans = traced(recent(201, 1520), "render.template", 0.95)  # the time is not in the database
    ingest_spans(client, spans)
    [inc] = run(client, baseline() + events)
    out = investigate(client, inc["id"])
    assert hyp(out["incident"], "slow_dependency")["status"] == "falsified"


def test_payment_failures_are_matched_through_traces_when_logs_are_missing(client):
    events, spans = traced(recent(504, 3004), "payment.authorize", 0.99, status_code=2)
    ingest_spans(client, spans)
    a_few = [line(NOW - timedelta(seconds=95), "/api/checkout", 504, 3004, "v1", "payment_timeout") for _ in range(1)]
    [inc] = run(client, baseline() + events, a_few)
    res = client.post(f"/api/v1/incidents/{inc['id']}/diagnostics", json={"test_id": "inspect_payment_provider_status_and_spans"}, headers=AUTH).json()
    r = next(x for x in res["diagnostic_runs"] if x["test_id"] == "inspect_payment_provider_status_and_spans")
    assert r["outcome"] == "supports" and r["details"]["matched_by_trace"] >= 8 and r["details"]["matched_by_log"] == 0


def test_decoy_release_during_a_slow_query_is_resolved_by_testing_the_alternative(client):
    """Reproduces a live campaign incident: a new release went out exactly as a slow-query fault began.
    The release test can only restate the coincidence, so it must not end the investigation; the
    dependency test (traces) then shows the time is in the database."""
    events, spans = traced(recent(201, 1520, version="v2"), "db.query orders.lookup", 0.95)
    ingest_spans(client, spans)
    [inc] = run(client, baseline() + events)
    out = investigate(client, inc["id"], budget=3)
    tested = [s["test_id"] for s in out["report"]["steps"]]
    assert "inspect_db_pool_wait_and_query_duration" in tested  # the alternative was tested
    assert out["incident"]["hypotheses"][0]["cause_key"] == "slow_dependency"
    release_run = next(r for r in out["incident"]["diagnostic_runs"] if r["test_id"] == "compare_error_rate_before_after_release")
    assert release_run["details"]["strength"] <= 0.4  # coincidence alone is weak for a slowdown


def test_diagnostics_rebuild_the_incident_with_its_own_analysis_window(client):
    """An earlier, unrelated slowdown sits inside the 900 s default lookback but outside this incident's
    300 s analysis window. Rebuilding with 900 s put it in the baseline and the incident vanished."""
    earlier = [line(NOW - timedelta(seconds=560 - i * 6), "/api/checkout", 201, 2600) | {"request_id": f"old{i}"} for i in range(25)]
    base = [line(NOW - timedelta(seconds=290 - i * 4), "/api/checkout", 201, 18 + i % 4) | {"request_id": f"b{i}"} for i in range(40)]
    slow = recent(201, 1520)
    events, spans = traced(slow, "db.query orders.lookup", 0.95)
    ingest_spans(client, spans)
    res = client.post("/api/v1/telemetry/events?adapter=shop_json", json={"events": earlier + base + events}, headers=AUTH)
    assert res.json()["rejected"] == 0
    [inc] = client.post("/api/v1/incidents/analyze", params={"as_of": NOW.isoformat(), "window_seconds": 300}, headers=AUTH).json()
    assert inc["summary"]["analysis_window_seconds"] == 300
    out = investigate(client, inc["id"])
    run_ = next(r for r in out["incident"]["diagnostic_runs"] if r["test_id"] == "inspect_db_pool_wait_and_query_duration")
    assert run_["outcome"] == "supports", run_["explanation"]
