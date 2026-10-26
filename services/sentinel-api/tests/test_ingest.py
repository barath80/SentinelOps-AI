from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.adapters import log_template
from app.config import Settings
from app.main import create_app

AUTH = {"Authorization": "Bearer test-token"}
URL = "/api/v1/telemetry/events"


@pytest.fixture()
def client(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 't.db'}", ingest_token="test-token", max_batch_events=5)
    return TestClient(create_app(settings))


def shop_line(**over):
    base = {
        "event_time": datetime.now(timezone.utc).isoformat(),
        "service_name": "shop-web",
        "environment": "production",
        "level": "info",
        "message": "request",
        "request_id": "r1",
        "route": "/api/checkout",
        "status": 200,
        "duration_ms": 12,
    }
    return {**base, **over}


def post(client, events, adapter="shop_json", headers=AUTH):
    return client.post(f"{URL}?adapter={adapter}", json={"events": events}, headers=headers)


def test_requires_token(client):
    assert post(client, [shop_line()], headers={}).status_code == 401
    assert post(client, [shop_line()], headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_fails_closed_without_configured_token(tmp_path):
    c = TestClient(create_app(Settings(database_url=f"sqlite:///{tmp_path / 'x.db'}", ingest_token="")))
    assert c.post(URL, json={"events": []}, headers={"Authorization": "Bearer "}).status_code == 401


def test_shop_event_is_normalized_and_stored(client):
    res = post(client, [shop_line(level="error", status=500)])
    assert res.json() == {"accepted": 1, "duplicates": 0, "rejected": 0, "errors": []}
    [event] = client.get(URL, headers=AUTH).json()
    assert event["service_name"] == "shop-web"
    assert event["event_type"] == "log"
    assert event["severity"] == "error"
    assert event["attributes"]["status"] == 500


def test_redelivery_is_idempotent(client):
    line = shop_line()
    assert post(client, [line]).json()["accepted"] == 1
    again = post(client, [line]).json()
    assert (again["accepted"], again["duplicates"]) == (0, 1)
    assert len(client.get(URL, headers=AUTH).json()) == 1


def test_duplicate_inside_one_batch(client):
    line = shop_line()
    assert post(client, [line, line]).json()["accepted"] == 1


def test_bad_records_are_rejected_not_fatal(client):
    res = post(client, [shop_line(), {"service_name": "x"}, shop_line(event_time="not-a-time", request_id="r2")]).json()
    assert (res["accepted"], res["rejected"]) == (1, 2)
    assert {e["index"] for e in res["errors"]} == {1, 2}


def test_naive_timestamp_rejected(client):
    res = post(client, [shop_line(event_time="2026-10-26T10:00:00")]).json()
    assert res["rejected"] == 1


def test_far_future_event_rejected_as_clock_skew(client):
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    res = post(client, [shop_line(event_time=future)]).json()
    assert res["rejected"] == 1 and "future" in res["errors"][0]["error"]


def test_batch_size_limit(client):
    res = post(client, [shop_line(request_id=f"r{i}") for i in range(6)])
    assert res.status_code == 413


def test_unknown_adapter(client):
    assert post(client, [], adapter="nope").status_code == 400


def test_text_adapter_extracts_time_level_and_template(client):
    lines = [
        {"line": "2026-10-26T10:00:00Z ERROR db pool exhausted: 50/50 connections for req 123", "service_name": "api"},
        {"line": "no timestamp here but WARN slow", "service_name": "api"},
    ]
    assert post(client, lines, adapter="text").json()["accepted"] == 2
    events = {e["attributes"]["message"]: e for e in client.get(URL, headers=AUTH).json()}
    first = events["ERROR db pool exhausted: 50/50 connections for req 123"]
    assert first["severity"] == "error"
    assert first["event_time"].startswith("2026-10-26T10:00:00")
    assert first["attributes"]["template"] == "ERROR db pool exhausted: <num>/<num> connections for req <num>"
    assert first["attributes"]["time_from_line"] is True
    assert events["no timestamp here but WARN slow"]["attributes"]["time_from_line"] is False


def test_log_template_collapses_uuid_and_hex():
    t = log_template("order 3f2b8c1e-1111-4222-8333-444455556666 failed at 0xdeadbeef after 250ms")
    assert t == "order <uuid> failed at <hex> after <num>ms"


def test_normalized_adapter_ignores_client_supplied_tenant(client):
    ev = {
        "event_id": "11111111-1111-4111-8111-111111111111",
        "tenant_id": "99999999-9999-4999-8999-999999999999",
        "environment": "demo",
        "service_name": "svc",
        "event_type": "metric",
        "event_time": datetime.now(timezone.utc).isoformat(),
        "source_ref": "prom:q1",
        "attributes": {"value": 1},
    }
    assert post(client, [ev], adapter="normalized").json()["accepted"] == 1
    assert len(client.get(URL, headers=AUTH).json()) == 1
