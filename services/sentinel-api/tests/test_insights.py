"""Timeline, similar incidents, postmortem draft, SLOs / error budgets and release markers."""
from datetime import timedelta

from app import insights
from app.db import EventRow
from tests.test_incidents import AUTH, NOW, baseline, line, recent, run
from tests.test_product import ALICE, BOB, add_channel, env, make, outbox, s01  # noqa: F401
from tests.test_recovery import feed, window


def resolve(client, inc):
    c = client.post("/api/v1/recovery-contracts", json={"incident_id": inc["id"]}, headers=ALICE).json()
    client.post(f"/api/v1/recovery-contracts/{c['id']}/approve", json={"decision": "approve"}, headers=BOB)
    done = client.post(f"/api/v1/recovery-contracts/{c['id']}/execute", headers=BOB).json()
    start, end = window(done)
    feed(client, start)
    v = client.post(f"/api/v1/recovery-contracts/{c['id']}/verify", params={"as_of": (end + timedelta(seconds=1)).isoformat()}, headers=BOB)
    assert v.json()["outcome"] == "pass"


def test_timeline_tells_the_incident_in_order(env):
    client, _ = env
    inc = s01(client)
    client.post(f"/api/v1/incidents/{inc['id']}/investigate", json={}, headers=AUTH)
    client.post("/api/v1/recovery-contracts", json={"incident_id": inc["id"]}, headers=ALICE)
    t = client.get(f"/api/v1/incidents/{inc['id']}/timeline", headers=AUTH).json()
    kinds = [x["kind"] for x in t]
    assert kinds.index("release") < kinds.index("detected") < kinds.index("diagnostic") < kinds.index("recovery")
    release = next(x for x in t if x["kind"] == "release")
    assert "release v2 first seen" in release["text"] and release["ref"]  # cites the event it was seen in
    assert any(x["kind"] == "recovery" and x["actor"] == "alice" for x in t)
    assert [x["at"] for x in t] == sorted(x["at"] for x in t)


def test_similar_incident_and_what_fixed_it(tmp_path):
    client, _ = make(tmp_path)
    first = s01(client)
    resolve(client, first)
    # the same fault again, a day later
    later = [e | {"event_time": (__import__("datetime").datetime.fromisoformat(e["event_time"]) + timedelta(days=1)).isoformat(),
                  "request_id": e["request_id"] + "-d2"}
             for e in baseline() + recent(500, 1, version="v2", message="unhandled_exception")]
    client.post("/api/v1/telemetry/events?adapter=shop_json", json={"events": later}, headers=AUTH)
    [second] = client.post("/api/v1/incidents/analyze", params={"as_of": (NOW + timedelta(days=1)).isoformat()}, headers=AUTH).json()
    sims = client.get(f"/api/v1/incidents/{second['id']}/similar", headers=AUTH).json()
    assert sims and sims[0]["incident_id"] == first["id"] and sims[0]["similarity"] > 0.95
    assert sims[0]["resolved_by"] == "rollback_release" and sims[0]["cause"] == "release_regression"


def test_postmortem_draft_cites_evidence(env):
    client, _ = env
    inc = s01(client)
    r = client.get(f"/api/v1/incidents/{inc['id']}/postmortem", headers=AUTH)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    md = r.text
    for section in ("# Postmortem (draft)", "## Impact", "## Root cause and evidence", "## Timeline (UTC)", "## What was done",
                    "## Open questions (missing evidence)"):
        assert section in md, section
    assert "release_regression" in md and "Sources: `" in md and "not a probability" in md


def test_postmortem_reports_the_verified_resolution(env):
    client, _ = env
    inc = s01(client)
    resolve(client, inc)
    md = client.get(f"/api/v1/incidents/{inc['id']}/postmortem", headers=AUTH).text
    assert "**Resolved (verified):**" in md and "final state **SUCCEEDED**" in md


def test_slo_error_budget_and_fast_burn(env):
    client, _ = env
    add_channel(client, events=["slo.burn"])
    burst = [line(NOW - timedelta(seconds=110 - i * 4), "/api/checkout", 500, 5) | {"request_id": f"x{i}"} for i in range(25)]
    run(client, baseline() + burst)
    with client.app.state.sessions() as s:
        rows = list(s.scalars(__import__("sqlalchemy").select(EventRow)))
    checkout = next(r for r in insights.slos(rows, NOW) if r["route"] == "/api/checkout")
    assert checkout["fast_burn"] and checkout["burn_rate_1h"] >= insights.FAST_BURN
    assert checkout["error_budget_remaining"] == 0.0 and checkout["availability_24h"] < 0.99
    products = next(r for r in insights.slos(rows, NOW) if r["route"] == "/api/products")
    assert not products["fast_burn"] and products["error_budget_remaining"] == 1.0
    assert any(n["event"] == "slo.burn" and "/api/checkout" in n["text"] for n in outbox(client))
    assert client.get("/api/v1/slo", headers=AUTH).status_code == 200


def test_release_markers_on_the_charts(env):
    client, _ = env
    s01(client)
    sr = client.get("/api/v1/telemetry/series", params={"until": NOW.isoformat(), "minutes": 15, "bucket_seconds": 60}, headers=AUTH).json()
    assert [r["version"] for r in sr["releases"]] == ["v2"]


def test_timeline_ignores_signals_from_an_earlier_unrelated_fault(env):
    client, _ = env
    old_timeout = line(NOW - timedelta(seconds=560), "/api/checkout", 504, 3000, message="payment_timeout") | {"request_id": "old"}
    [inc] = run(client, baseline() + recent(500, 1, version="v2", message="unhandled_exception"), [old_timeout])
    t = client.get(f"/api/v1/incidents/{inc['id']}/timeline", headers=AUTH).json()
    assert not any(x["kind"] == "signal" for x in t)
