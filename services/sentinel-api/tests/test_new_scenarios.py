"""Scenarios S02 (pool exhaustion), S04 (cache down), S06 (CPU saturation), S07 (retry storm) and
S11 (clock skew), driven through the API with logs plus traces in the shape the shop emits."""
from datetime import datetime, timedelta, timezone

from tests.test_diagnostics import hyp, ingest_spans, investigate
from tests.test_incidents import AUTH, NOW, baseline, client, line, recent, run  # noqa: F401


def with_traces(events, children, root_attrs=None, start_index=0):
    """Give each request a trace: a root span plus `children(event)` -> [(name, ms, status_code)]."""
    spans = []
    for i, e in enumerate(events, start=start_index):
        tid = f"{i + 1:032x}"
        e["trace_id"] = tid
        start = int(datetime.fromisoformat(e["event_time"]).timestamp() * 1e9)
        dur = int(e["duration_ms"] * 1e6)
        root_id = f"{i + 1:016x}"
        attrs = {"http.route": e["route"], **((root_attrs or (lambda _e: {}))(e))}
        spans.append({"traceId": tid, "spanId": root_id, "name": f"{e['method']} {e['route']}", "serviceName": "shop-web",
                      "startTimeUnixNano": start, "endTimeUnixNano": start + dur,
                      "status": {"code": 2 if e["status"] >= 500 else 1}, "attributes": attrs})
        offset = start
        for j, (name, ms, code) in enumerate(children(e)):
            spans.append({"traceId": tid, "spanId": f"{i + 1:012x}{j + 1:04x}", "parentSpanId": root_id, "name": name,
                          "serviceName": "shop-web", "startTimeUnixNano": offset, "endTimeUnixNano": offset + int(ms * 1e6),
                          "status": {"code": code}})
            offset += int(ms * 1e6)
    return events, spans


def healthy_children(e):
    if e["route"] == "/api/checkout":
        return [("db.pool.acquire", 1, 1), ("db.query orders.lookup", 6, 1), ("payment.authorize", 4, 1), ("db.query orders.insert", 5, 1)]
    return [("cache.get catalogue", 1, 1)]


def traced_baseline():
    return with_traces(baseline(), healthy_children, lambda e: {"cpu_ms": 3})


def analyse(client, recent_events, recent_spans, extra=()):
    base, base_spans = traced_baseline()
    ingest_spans(client, base_spans + recent_spans)
    return run(client, base + recent_events, list(extra))


def steps_of(out):
    return [s["test_id"] for s in out["report"]["steps"]]


def test_s02_pool_exhaustion_is_separated_from_a_slow_query(client):
    events, spans = with_traces(recent(201, 1520), lambda e: [("db.pool.acquire", 1300, 1), ("db.query orders.lookup", 8, 1),
                                                                ("payment.authorize", 4, 1), ("db.query orders.insert", 6, 1)],
                                start_index=500)
    [inc] = analyse(client, events, spans)
    out = investigate(client, inc["id"])
    assert hyp(out["incident"], "slow_dependency")["status"] == "falsified"  # the queries themselves are fast
    assert out["incident"]["hypotheses"][0]["cause_key"] == "db_pool_exhaustion"
    assert out["incident"]["assessment"] == "leading_hypothesis"
    assert "inspect_db_pool_acquire_wait" in steps_of(out)


def test_s03_slow_query_is_not_mistaken_for_pool_exhaustion(client):
    events, spans = with_traces(recent(201, 1520), lambda e: [("db.pool.acquire", 1, 1), ("db.query orders.lookup", 1450, 1),
                                                                ("payment.authorize", 4, 1)], start_index=500)
    [inc] = analyse(client, events, spans)
    out = investigate(client, inc["id"])
    assert out["incident"]["hypotheses"][0]["cause_key"] == "slow_dependency"
    assert out["report"]["stop_reason"] == "leader_survived_falsification"


def test_s04_cache_outage_on_the_products_route(client):
    slow_products = [line(NOW - timedelta(seconds=100 - i * 9), "/api/products", 200, 620, method="GET") | {"request_id": f"p{i}"}
                     for i in range(10)]
    checkout_ok = [line(NOW - timedelta(seconds=96 - i * 9), "/api/checkout", 201, 20) | {"request_id": f"c{i}"} for i in range(10)]
    events, spans = with_traces(slow_products + checkout_ok,
                                lambda e: [("cache.get catalogue", 250, 2)] if e["route"] == "/api/products" else healthy_children(e),
                                start_index=500)
    [inc] = analyse(client, events, spans)
    assert inc["routes"] == ["/api/products"]
    out = investigate(client, inc["id"])
    assert out["incident"]["hypotheses"][0]["cause_key"] == "cache_unavailable", steps_of(out)
    assert out["incident"]["assessment"] == "leading_hypothesis"


def test_s06_cpu_saturation_slows_every_route(client):
    rec = []
    for i in range(10):
        t = NOW - timedelta(seconds=100 - i * 9)
        rec.append(line(t, "/api/checkout", 201, 900) | {"request_id": f"c{i}"})
        rec.append(line(t + timedelta(seconds=1), "/api/products", 200, 880, method="GET") | {"request_id": f"p{i}"})
    events, spans = with_traces(rec, healthy_children, lambda e: {"cpu_ms": round(e["duration_ms"] * 0.9, 1)}, start_index=500)
    [inc] = analyse(client, events, spans)
    assert set(inc["routes"]) == {"/api/checkout", "/api/products"}
    out = investigate(client, inc["id"])
    assert out["incident"]["hypotheses"][0]["cause_key"] == "resource_saturation", steps_of(out)
    run_ = next(r for r in out["incident"]["diagnostic_runs"] if r["test_id"] == "inspect_cpu_time")
    assert run_["outcome"] == "supports" and run_["details"]["median_share_on_cpu"] >= 0.8


def test_s07_retry_storm_is_not_called_a_payment_timeout(client):
    rec = []
    for i in range(10):
        t = NOW - timedelta(seconds=100 - i * 9)
        status = 502 if i % 3 == 0 else 201
        rec.append(line(t, "/api/checkout", status, 1650) | {"request_id": f"c{i}"})
    events, spans = with_traces(rec, lambda e: [("payment.authorize", 400, 2)] * 4 + [("payment.authorize", 5, 1 if e["status"] < 500 else 2)],
                                start_index=500)
    retries = [line(datetime.fromisoformat(e["event_time"]) + timedelta(milliseconds=50 * k), "/api/checkout", 201, 0,
                    message="payment_retry", attempt=k) | {"request_id": e["request_id"], "level": "warning"}
               for e in rec for k in range(1, 5)]
    [inc] = analyse(client, events, spans, retries)
    out = investigate(client, inc["id"])
    assert out["incident"]["hypotheses"][0]["cause_key"] == "retry_storm", steps_of(out)
    run_ = next(r for r in out["incident"]["diagnostic_runs"] if r["test_id"] == "inspect_retry_amplification")
    assert run_["outcome"] == "supports" and run_["details"]["median_provider_calls_per_request"] >= 3
    assert hyp(out["incident"], "payment_provider_timeout")["status"] in ("falsified", "unlikely")


def test_hung_payment_still_matches_the_timeout_signature(client):
    events, spans = with_traces(recent(504, 3004), lambda e: [("payment.authorize", 3000, 2)], start_index=500)
    [inc] = analyse(client, events, spans)
    res = client.post(f"/api/v1/incidents/{inc['id']}/diagnostics", json={"test_id": "inspect_payment_provider_status_and_spans"},
                      headers=AUTH).json()
    r = next(x for x in res["diagnostic_runs"] if x["test_id"] == "inspect_payment_provider_status_and_spans")
    assert r["outcome"] == "supports" and r["details"]["matched_by_trace"] == 10


def test_s11_clock_ahead_is_reported_and_raises_no_incident(client):
    now = datetime.now(timezone.utc)
    skewed = [line(now + timedelta(seconds=240 + i), "/api/checkout", 201, 20) | {"request_id": f"s{i}"} for i in range(12)]
    normal = [line(now - timedelta(seconds=30 + i), "/api/products", 200, 9) | {"request_id": f"n{i}"} for i in range(6)]
    r = client.post("/api/v1/telemetry/events?adapter=shop_json", json={"events": skewed + normal}, headers=AUTH)
    assert r.json()["accepted"] == 18  # kept, not rejected: the problem must stay visible
    q = client.get("/api/v1/telemetry/quality", headers=AUTH).json()
    assert q["status"] == "clock_skew" and q["warnings"][0]["service"] == "shop-web"
    assert q["warnings"][0]["median_seconds"] >= 230 and q["services"]["shop-web"]["ahead_of_arrival"] == 12
    out = client.post("/api/v1/incidents/analyze", headers=AUTH).json()
    assert out == []


def test_quality_is_ok_for_normal_telemetry_and_recorded_on_incidents(client):
    [inc] = run(client, baseline() + recent(500, 1, version="v2", message="unhandled_exception"))
    assert inc["summary"]["telemetry_quality"]["status"] == "ok"
    assert client.get("/api/v1/telemetry/quality").status_code == 401


def test_new_causes_have_safe_recommended_actions_with_reverts(client):
    cat = client.get("/api/v1/recovery-actions", headers=AUTH).json()
    by_id = {a["id"]: a for a in cat["actions"]}
    for cause in ("db_pool_exhaustion", "cache_unavailable", "resource_saturation", "retry_storm"):
        action = by_id[cat["recommended_for_cause"][cause]]
        assert "production" not in action["environments"] and action["rollback_template"] in by_id


# ---- failure propagation ----------------------------------------------------------------------

def test_propagation_points_at_the_pool_for_s02(client):
    events, spans = with_traces(recent(201, 1520), lambda e: [("db.pool.acquire", 1300, 1), ("db.query orders.lookup", 8, 1),
                                                                ("payment.authorize", 4, 1)], start_index=500)
    [inc] = analyse(client, events, spans)
    prop = inc["summary"]["propagation"]
    assert prop["traced"] and prop["earliest_containment"]["node"] == "postgres-pool"
    assert prop["earliest_containment"]["edge"] == ["/api/checkout"]
    edge = next(e for e in prop["edges"] if e["from"] == "/api/checkout" and e["to"] == "postgres-pool")
    assert edge["kind"] == "observed" and edge["anomalous"] and edge["recent_median_ms"] >= 1300
    query = next(e for e in prop["edges"] if e["from"] == "/api/checkout" and e["to"] == "postgres")
    assert not query["anomalous"]  # the queries themselves are fine
    assert prop["order"][0] == "postgres-pool"


def test_propagation_for_a_code_fault_blames_the_route_not_a_dependency(client):
    rec = recent(500, 1, version="v2", message="unhandled_exception")
    events, spans = with_traces(rec, lambda e: [] if e["route"] == "/api/checkout" else healthy_children(e), start_index=500)
    [inc] = analyse(client, events, spans)
    prop = inc["summary"]["propagation"]
    assert prop["earliest_containment"]["node"] == "service-code"
    reached = {e["to"]: e["kind"] for e in prop["edges"] if e["from"] == "/api/checkout"}
    assert reached["postgres"] == "not_reached"  # the code now throws before it queries


def test_propagation_without_traces_says_so(client):
    [inc] = run(client, baseline() + recent(500, 1, version="v2", message="unhandled_exception"))
    prop = inc["summary"]["propagation"]
    assert prop["traced"] is False and all(e["kind"] == "no_traces" for e in prop["edges"])
    assert "not proof" in prop["note"]


def test_propagation_for_retry_storm_points_at_the_provider(client):
    rec = [line(NOW - timedelta(seconds=100 - i * 9), "/api/checkout", 502 if i % 3 == 0 else 201, 1650) | {"request_id": f"c{i}"}
           for i in range(10)]
    events, spans = with_traces(rec, lambda e: [("payment.authorize", 400, 2)] * 4, start_index=500)
    [inc] = analyse(client, events, spans)
    assert inc["summary"]["propagation"]["earliest_containment"]["node"] == "payment-provider"
