"""Labelled-incident campaign against a running shop and SentinelOps API.

Each run: healthy baseline traffic -> wait until it is older than the detection window -> traffic
with ONE scoped fault (or none / a traffic surge) -> ask SentinelOps to analyse -> label the incident
it raised with the ground truth this runner knows. Faults are scoped to the runner's own requests
through the shop's chaos headers, so real visitors are never affected, and the chaos headers are
never logged by the shop, so SentinelOps cannot see the answer.

Usage:
  set CHAOS_TOKEN=...      (must equal the shop's CHAOS_TOKEN)
  set SENTINEL_TOKEN=...   (SentinelOps machine token: ingest, read, analysis)
  set SENTINEL_OPERATOR=campaign  and  SENTINEL_OPERATOR_PASSWORD=...
                           (an operator with the responder role: labels are recorded under it.
                            Not needed when the API runs in legacy shared_token mode.)
  python -m campaign.run_campaign --shop https://shop.example --sentinel https://sentinel.example \
      --scenarios S01 S03 S05 S08 none surge --runs 2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

SCENARIOS = {
    "S01": ("S01_bad_deployment", "release_regression"),
    "S02": ("S02_db_pool_exhaustion", "db_pool_exhaustion"),
    "S03": ("S03_slow_query", "slow_dependency"),
    "S04": ("S04_cache_unavailable", "cache_unavailable"),
    "S05": ("S05_payment_timeout", "payment_provider_timeout"),
    "S06": ("S06_cpu_saturation", "resource_saturation"),
    "S07": ("S07_retry_storm", "retry_storm"),
    "S08": ("S08_plain_errors", "unknown"),
    # The shop is healthy but its clock runs 4 minutes ahead: the right answer is no incident plus a
    # telemetry-quality warning. Run it last: its future-stamped events land in the next run's baseline.
    "S11": ("S11_clock_skew", "no_fault"),
    "none": (None, "no_fault"),     # healthy traffic: any incident raised is a false alarm
    "surge": (None, "traffic_surge"),  # no fault header, but six times the request rate
}
DETECTION_WINDOW_S = 120
# SentinelOps treats anomalies within 2 x 120 s of an open incident as the same incident, so runs
# must start their faults further apart than that, or a later run would refresh an earlier incident.
COOLDOWN_S = 75


def aware(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite returns naive UTC


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc):%H:%M:%S} {msg}", flush=True)


class Shopper:
    """One round = browse products, add to cart, check out (the same journey the benchmark uses)."""

    def __init__(self, base: str, chaos_token: str | None):
        self.base, self.chaos_token = base.rstrip("/"), chaos_token

    def round(self, scenario: str | None) -> int:
        headers = {}
        if scenario:
            headers = {"x-chaos-token": self.chaos_token or "", "x-chaos-scenario": scenario}
        with httpx.Client(base_url=self.base, timeout=30, headers=headers) as c:
            try:
                c.get("/api/products")
                c.post("/api/cart", json={"id": "p2", "qty": 1})
                return c.post("/api/checkout", headers={"idempotency-key": f"campaign-{uuid.uuid4()}"}).status_code
            except httpx.HTTPError:
                return 0


class Sentinel:
    def __init__(self, base: str, token: str, operator: str | None = None, password: str | None = None):
        self.base, self.headers = base.rstrip("/"), {"Authorization": f"Bearer {token}"}
        self.person = {"X-Actor": "campaign"}  # legacy shared_token mode
        if operator and password:
            r = httpx.post(self.base + "/api/v1/auth/login", json={"username": operator, "password": password}, timeout=60)
            r.raise_for_status()
            self.person = {"Authorization": f"Bearer {r.json()['token']}"}

    def call(self, method: str, path: str, **kw):
        last = None
        for attempt in range(4):  # some networks reset a share of connections; retry with backoff
            try:
                r = httpx.request(method, self.base + path, headers={**self.headers, **kw.pop("headers", {})}, timeout=120, **kw)
                r.raise_for_status()
                return r.json()
            except (httpx.HTTPError, ValueError) as exc:
                last = exc
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"{method} {path} failed: {last}")


def traffic(shopper: Shopper, rounds: int, scenario: str | None, workers: int = 1, pause: float = 0.25) -> list[int]:
    if workers == 1:
        out = []
        for _ in range(rounds):
            out.append(shopper.round(scenario))
            time.sleep(pause)
        return out
    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(lambda _: shopper.round(scenario), range(rounds)))


def run_once(key: str, shopper: Shopper, sentinel: Sentinel, investigate: bool, baseline_rounds: int, fault_rounds: int,
             labelled: set[str]) -> dict:
    header_scenario, truth = SCENARIOS[key]
    run_id = uuid.uuid4().hex[:8]
    start = datetime.now(timezone.utc)
    log(f"[{run_id}] {key}: baseline ({baseline_rounds} rounds)")
    base_codes = traffic(shopper, baseline_rounds, None)
    wait = DETECTION_WINDOW_S + 5
    log(f"[{run_id}] waiting {wait}s so the baseline is older than the detection window")
    time.sleep(wait)
    fault_start = datetime.now(timezone.utc)
    if key == "surge":
        codes = traffic(shopper, fault_rounds * 6, None, workers=6)
    else:
        codes = traffic(shopper, fault_rounds, header_scenario)
    time.sleep(6)  # let the shop flush its telemetry
    as_of = datetime.now(timezone.utc)
    window = int((as_of - start).total_seconds()) + 5
    incidents = sentinel.call("POST", f"/api/v1/incidents/analyze?window_seconds={window}&as_of={as_of.isoformat().replace('+', '%2B')}")
    mine = [i for i in incidents if aware(i["started_at"]) >= fault_start - timedelta(seconds=10)]
    reused = [i["id"] for i in mine if i["id"] in labelled]
    mine = [i for i in mine if i["id"] not in labelled]  # never relabel an earlier run's incident
    result = {"run_id": run_id, "scenario": key, "truth": truth, "started": start.isoformat(),
              "baseline_ok": sum(c == 201 for c in base_codes), "fault_status_codes": sorted(set(codes)),
              "detected": bool(mine), "incidents": [], "skipped_already_labelled": reused}
    for inc in mine:
        labelled.add(inc["id"])
        report = None
        if investigate:
            report = sentinel.call("POST", f"/api/v1/incidents/{inc['id']}/investigate", json={"budget": 4})["report"]
        sentinel.call("POST", f"/api/v1/incidents/{inc['id']}/label", headers=sentinel.person,
                      json={"label": truth, "note": f"campaign run {run_id}: {key} ({header_scenario or 'no fault header'})"})
        shadow = (inc["summary"].get("shadow_model") or {})
        containment = (inc["summary"].get("propagation") or {}).get("earliest_containment") or {}
        result["incidents"].append({"id": inc["id"], "title": inc["title"], "rule_answer": inc["summary"].get("rule_answer"),
                                    "investigated_answer": (report["leader"] if report and report["assessment"] == "leading_hypothesis"
                                                            else ("unknown" if report else None)),
                                    "stop_reason": report["stop_reason"] if report else None,
                                    "tests": [st["test_id"] for st in report["steps"]] if report else [],
                                    "containment": containment.get("node"),
                                    "shadow_prediction": shadow.get("prediction"), "shadow_top": shadow.get("top_class"),
                                    "shadow_confidence": shadow.get("confidence")})
    result["telemetry_quality"] = sentinel.call("GET", "/api/v1/telemetry/quality?window_seconds=600")["status"]
    verdict = ", ".join(f"rules={i['rule_answer']} investigated={i['investigated_answer']} contain={i['containment']} "
                        f"shadow={i['shadow_prediction']}" for i in result["incidents"]) or "no incident"
    verdict += f"; telemetry {result['telemetry_quality']}"
    log(f"[{run_id}] {key} (truth {truth}): {verdict}")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shop", required=True)
    ap.add_argument("--sentinel", required=True)
    ap.add_argument("--scenarios", nargs="+", default=list(SCENARIOS), choices=list(SCENARIOS))
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--baseline-rounds", type=int, default=60)
    ap.add_argument("--fault-rounds", type=int, default=14)
    ap.add_argument("--investigate", action="store_true")
    ap.add_argument("--out", default="campaign/results/campaign.jsonl")
    args = ap.parse_args()

    chaos, token = os.environ.get("CHAOS_TOKEN"), os.environ.get("SENTINEL_TOKEN")
    if not token:
        sys.exit("set SENTINEL_TOKEN")
    if not chaos and any(SCENARIOS[s][0] for s in args.scenarios):
        sys.exit("set CHAOS_TOKEN (the shop's CHAOS_TOKEN) to inject scoped faults")
    shopper = Shopper(args.shop, chaos)
    sentinel = Sentinel(args.sentinel, token, os.environ.get("SENTINEL_OPERATOR"), os.environ.get("SENTINEL_OPERATOR_PASSWORD"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    plan = [s for _ in range(args.runs) for s in args.scenarios]
    plan = [s for s in plan if s != "S11"] + [s for s in plan if s == "S11"]  # see SCENARIOS
    log(f"campaign: {len(plan)} runs, about {len(plan) * 4.7:.0f} minutes")
    labelled: set[str] = set()
    for key in plan:
        try:
            res = run_once(key, shopper, sentinel, args.investigate, args.baseline_rounds, args.fault_rounds, labelled)
        except Exception as exc:  # noqa: BLE001 - one failed run must not lose the campaign
            log(f"run {key} failed: {exc}")
            res = {"scenario": key, "error": str(exc)}
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(res) + "\n")
        time.sleep(COOLDOWN_S)  # keep runs far enough apart that they never share an incident
    log("campaign finished; results in " + str(out))


if __name__ == "__main__":
    main()
