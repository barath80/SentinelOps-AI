"""End-to-end tests: ingest synthetic shop logs, run analysis, check incidents and evidence."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

AUTH = {"Authorization": "Bearer test-token"}
NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def client(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 't.db'}", ingest_token="test-token", max_batch_events=2000)
    return TestClient(create_app(settings))


def line(t, route, status, duration, version="v1", message=None, **extra):
    return {
        "event_time": t.isoformat(), "service_name": "shop-web", "environment": "production",
        "level": "error" if status >= 500 else "info", "version": version,
        "message": message or "request", "request_id": f"r-{t.timestamp():.3f}-{route}",
        "route": route, "method": "POST", "status": status, "duration_ms": duration, **extra,
    }


def baseline():
    """~8 minutes of healthy traffic ending 130 s before NOW."""
    out = []
    for i in range(60):
        t = NOW - timedelta(seconds=600 - i * 7)
        out.append(line(t, "/api/checkout", 201, 18 + (i % 5)))
        out.append(line(t + timedelta(seconds=1), "/api/products", 200, 8 + (i % 3)))
    return out


def recent(checkout_status, duration, version="v1", message=None, n=10, products=True, **extra):
    out = []
    for i in range(n):
        t = NOW - timedelta(seconds=100 - i * 9)
        out.append(line(t, "/api/checkout", checkout_status, duration, version, message, **extra))
        if products:
            out.append(line(t + timedelta(seconds=1), "/api/products", 200, 9))
    return out


def run(client, events, extra_events=()):
    res = client.post("/api/v1/telemetry/events?adapter=shop_json", json={"events": events + list(extra_events)}, headers=AUTH)
    assert res.status_code == 200 and res.json()["rejected"] == 0, res.text
    out = client.post("/api/v1/incidents/analyze", params={"as_of": NOW.isoformat()}, headers=AUTH)
    assert out.status_code == 200, out.text
    return out.json()


def leading(incident):
    return incident["hypotheses"][0]


def test_healthy_traffic_creates_no_incident(client):
    assert run(client, baseline() + recent(201, 20)) == []


def test_too_little_recent_data_is_not_an_incident(client):
    assert run(client, baseline() + recent(500, 2, n=2)) == []


def test_s01_bad_deployment(client):
    events = baseline() + recent(500, 1, version="v2", message="unhandled_exception", error="TypeError: x")
    [inc] = run(client, events)
    assert inc["severity"] == "critical" and inc["assessment"] == "leading_hypothesis"
    top = leading(inc)
    assert top["cause_key"] == "release_regression" and top["status"] == "leading"
    assert top["score_is_probability"] is False
    relations = {e["relation"] for e in top["evidence"]}
    assert {"supports", "missing"} <= relations
    # the unaffected route is reported
    assert inc["summary"]["unaffected_routes"] == ["/api/products"]


def test_s05_payment_timeout(client):
    timeouts = [line(NOW - timedelta(seconds=90 - i * 9), "/api/checkout", 504, 3004, message="payment_timeout") for i in range(10)]
    [inc] = run(client, baseline() + recent(504, 3004), timeouts)
    top = leading(inc)
    assert top["cause_key"] == "payment_provider_timeout" and top["status"] == "leading"
    release = next(h for h in inc["hypotheses"] if h["cause_key"] == "release_regression")
    assert any(e["relation"] == "contradicts" for e in release["evidence"])  # same version as baseline


def test_s03_slow_but_succeeding_points_to_slow_dependency(client):
    [inc] = run(client, baseline() + recent(201, 1520))
    assert inc["severity"] == "warning" and inc["summary"]["anomalies"][0]["kind"] == "latency"
    top = leading(inc)
    assert top["cause_key"] == "slow_dependency"
    missing = [e for e in top["evidence"] if e["relation"] == "missing"]
    assert missing and "database" in missing[0]["explanation"].lower()
    # a cause with no supporting evidence must not score as a live alternative
    payment = next(h for h in inc["hypotheses"] if h["cause_key"] == "payment_provider_timeout")
    assert payment["score"] < 0 and payment["status"] == "unlikely"


def test_decoy_deployment_does_not_win_over_timeouts(client):
    """A release label changed, but the failures are payment timeouts: the decoy must not lead."""
    timeouts = [line(NOW - timedelta(seconds=90 - i * 9), "/api/checkout", 504, 3004, "v2", "payment_timeout") for i in range(10)]
    [inc] = run(client, baseline() + recent(504, 3004, version="v2"), timeouts)
    assert leading(inc)["cause_key"] == "payment_provider_timeout"
    release = next(h for h in inc["hypotheses"] if h["cause_key"] == "release_regression")
    assert release["status"] != "leading"
    assert any(e["relation"] == "supports" for e in release["evidence"])  # considered, then outranked


def test_ambiguous_case_abstains(client):
    """Errors with no version change, no exceptions, no timeouts: do not force a cause."""
    [inc] = run(client, baseline() + recent(500, 40))
    assert inc["assessment"] == "inconclusive"
    assert leading(inc)["status"] == "uncertain"


def test_reanalysis_is_idempotent(client):
    events = baseline() + recent(500, 1, version="v2", message="unhandled_exception")
    [first] = run(client, events)
    again = client.post("/api/v1/incidents/analyze", params={"as_of": NOW.isoformat()}, headers=AUTH).json()
    assert [i["id"] for i in again] == [first["id"]]
    assert len(client.get("/api/v1/incidents", headers=AUTH).json()) == 1


def test_evidence_sources_resolve_to_stored_events(client):
    [inc] = run(client, baseline() + recent(500, 1, version="v2", message="unhandled_exception"))
    stored = {e["event_id"] for e in client.get("/api/v1/telemetry/events?limit=200", headers=AUTH).json()}
    refs = [r for h in inc["hypotheses"] for e in h["evidence"] for r in e["source_refs"]]
    assert refs, "supporting evidence should cite events"
    assert set(refs) <= stored


def test_incident_endpoints_require_auth_and_404_unknown(client):
    assert client.get("/api/v1/incidents").status_code == 401
    assert client.post("/api/v1/incidents/analyze").status_code == 401
    assert client.get("/api/v1/incidents/does-not-exist", headers=AUTH).status_code == 404


def test_get_incident_detail(client):
    [inc] = run(client, baseline() + recent(500, 1, version="v2", message="unhandled_exception"))
    got = client.get(f"/api/v1/incidents/{inc['id']}", headers=AUTH).json()
    assert got["id"] == inc["id"] and len(got["hypotheses"]) == 8


# ---- multi-symptom attribution -----------------------------------------------------------------

def two_fault_events(products_label):
    """Checkout throws on the new release; the products route is slow. `products_label` is the
    release label seen on the slow products requests."""
    events = baseline()
    for i in range(10):
        t = NOW - timedelta(seconds=100 - i * 9)
        events.append(line(t, "/api/checkout", 500, 1, "v2", "unhandled_exception", error="TypeError"))
        events.append(line(t + timedelta(seconds=1), "/api/products", 200, 1400, products_label))
        events.append(line(t + timedelta(seconds=2), "/api/cart", 200, 6, products_label))  # healthy third route
    for i in range(30):  # the cart route also has a baseline
        events.append(line(NOW - timedelta(seconds=600 - i * 15), "/api/cart", 200, 6))
    return events


def test_two_independent_faults_are_reported_as_multi_cause(client):
    """Products is slow on the OLD release while checkout fails on the new one: two causes."""
    [inc] = run(client, two_fault_events("v1"))
    s = inc["summary"]
    assert s["attribution"] == "multi_cause"
    assert s["causes"] == ["release_regression", "slow_dependency"]
    by_route = {x["route"]: x["cause"] for x in s["symptoms"]}
    assert by_route == {"/api/checkout": "release_regression", "/api/products": "slow_dependency"}


def test_a_symptom_that_cannot_be_attributed_is_reported_unexplained(client):
    """Slowness appears together with a release change, but nothing separates the two causes."""
    [inc] = run(client, two_fault_events("v2"))
    s = inc["summary"]
    assert s["attribution"] == "partial"
    assert s["causes"] == ["release_regression"] and s["unexplained_symptoms"] == ["/api/products (latency)"]


def test_single_symptom_incidents_are_single_cause(client):
    [inc] = run(client, baseline() + recent(500, 1, version="v2", message="unhandled_exception"))
    assert inc["summary"]["attribution"] == "single_cause" and inc["summary"]["causes"] == ["release_regression"]


def test_ambiguous_single_symptom_is_unexplained(tmp_path):
    from app.config import Settings
    from app.main import create_app
    c = TestClient(create_app(Settings(database_url=f"sqlite:///{tmp_path / 'a.db'}", ingest_token="test-token", max_batch_events=2000)))
    [inc] = run(c, baseline() + recent(500, 40))
    assert inc["summary"]["attribution"] == "unexplained" and inc["summary"]["causes"] == []
