"""End-to-end recovery check against a running shop and SentinelOps API with the shop_admin executor.

For each scenario: healthy baseline -> switch the shop's fault on (admin endpoint) -> fault traffic
-> analyse and investigate (machine token) -> propose (responder) -> approve (a different operator
with the approver role) -> execute (the real executor switches the fault off) -> traffic through the
verification window -> verify. Pass means the contract ends SUCCEEDED from measured telemetry.

With --rollback, the run instead starves the verification window of traffic so the verdict is
INCONCLUSIVE, rolls the contract back, and checks that the shop's fault is really active again
(read back through the admin endpoint and observed on a live request).

The fault is switched globally on the shop instance, so point this at a shop nobody else uses.

  set SHOP_ADMIN_TOKEN=...  SENTINEL_TOKEN=...  (machine token)
  set SENTINEL_RESPONDER=name:password  SENTINEL_APPROVER=name:password
  python -m campaign.e2e_recovery --shop http://localhost:3101 --sentinel http://localhost:8125 --scenarios S01 S02 ...
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from .run_campaign import DETECTION_WINDOW_S, SCENARIOS, Shopper, aware, log, traffic


class Api:
    def __init__(self, base: str, token: str):
        self.base, self.token = base.rstrip("/"), token

    def call(self, method: str, path: str, auth: str | None = None, ok=(200, 201), **kw) -> tuple[int, dict]:
        r = httpx.request(method, self.base + path, headers={"Authorization": f"Bearer {auth or self.token}"}, timeout=120, **kw)
        body = r.json() if r.content else {}
        if r.status_code not in ok:
            raise RuntimeError(f"{method} {path} -> {r.status_code} {body}")
        return r.status_code, body

    def login(self, cred: str) -> str:
        user, password = cred.split(":", 1)
        return self.call("POST", "/api/v1/auth/login", json={"username": user, "password": password})[1]["token"]


def set_fault(shop: str, token: str, scenario: str) -> str:
    r = httpx.post(f"{shop}/api/admin/fault", json={"scenario": scenario}, headers={"x-admin-token": token}, timeout=30)
    r.raise_for_status()
    return r.json()["active"]


def get_fault(shop: str, token: str) -> str:
    return httpx.get(f"{shop}/api/admin/fault", headers={"x-admin-token": token}, timeout=30).json()["active"]


def run_one(key: str, args, api: Api, responder: str, approver: str, admin_token: str, rollback: bool) -> dict:
    scenario, truth = SCENARIOS[key]
    shopper = Shopper(args.shop, None)
    out: dict = {"scenario": key, "truth": truth, "mode": "rollback" if rollback else "recover"}
    set_fault(args.shop, admin_token, "none")
    start = datetime.now(timezone.utc)
    log(f"{key}: baseline")
    traffic(shopper, args.baseline_rounds, None)
    time.sleep(DETECTION_WINDOW_S + 5)
    fault_start = datetime.now(timezone.utc)
    out["fault_active"] = set_fault(args.shop, admin_token, scenario)
    traffic(shopper, args.fault_rounds, None)
    time.sleep(6)
    as_of = datetime.now(timezone.utc)
    window = int((as_of - start).total_seconds()) + 5
    _, incidents = api.call("POST", f"/api/v1/incidents/analyze?window_seconds={window}&as_of={as_of.isoformat().replace('+', '%2B')}")
    mine = [i for i in incidents if aware(i["started_at"]) >= fault_start - timedelta(seconds=10)]
    if not mine:
        set_fault(args.shop, admin_token, "none")
        return {**out, "result": "no_incident"}
    inc = mine[0]
    _, inv = api.call("POST", f"/api/v1/incidents/{inc['id']}/investigate", json={"budget": 4})
    containment = (inc["summary"].get("propagation") or {}).get("earliest_containment") or {}
    out.update(incident=inc["id"], answer=inv["report"]["leader"] if inv["report"]["assessment"] == "leading_hypothesis" else None,
               stop_reason=inv["report"]["stop_reason"], containment=containment.get("node"))
    status, c = api.call("POST", "/api/v1/recovery-contracts", auth=responder, json={"incident_id": inc["id"]}, ok=(201, 403, 409))
    if status != 201:
        set_fault(args.shop, admin_token, "none")
        return {**out, "result": f"no_contract: {c.get('error')}"}
    out.update(action=c["action_template"], rehearsal=c["contract"]["rehearsal"]["outcome"])
    ack = c["contract"]["rehearsal"]["outcome"] == "fail"
    api.call("POST", f"/api/v1/recovery-contracts/{c['id']}/approve", auth=approver,
             json={"decision": "approve", "comment": "e2e", "acknowledge_rehearsal_failure": ack})
    _, done = api.call("POST", f"/api/v1/recovery-contracts/{c['id']}/execute", auth=responder)
    out.update(executed_state=done["state"], fault_after_action=get_fault(args.shop, admin_token))
    if done["state"] != "VERIFYING":
        return {**out, "result": "action_failed"}
    end = datetime.fromisoformat(done["contract"]["verification_window"]["end"])
    if rollback:
        traffic(shopper, 2, None)  # far too few samples: the verdict must be inconclusive
    else:
        while datetime.now(timezone.utc) < end + timedelta(seconds=2):
            traffic(shopper, 1, None)
    while datetime.now(timezone.utc) < end + timedelta(seconds=3):
        time.sleep(1)
    time.sleep(6)  # telemetry flush
    _, v = api.call("POST", f"/api/v1/recovery-contracts/{c['id']}/verify", auth=responder)
    out.update(verification=v["outcome"], verification_reason=v["reason"], final_state=v["state"])
    if rollback:
        _, rb = api.call("POST", f"/api/v1/recovery-contracts/{c['id']}/rollback", auth=responder,
                         json={"reason": "e2e: verification inconclusive"})
        check = rb["rollback_run"]["output"].get("verification", {})
        t0 = time.perf_counter()
        code = shopper.round(None)  # the restored fault should be visible on a real request again
        out.update(final_state=rb["state"], rollback_verified=check.get("restored"),
                   fault_after_rollback=get_fault(args.shop, admin_token),
                   live_round_after_rollback={"status": code, "seconds": round(time.perf_counter() - t0, 2)})
    set_fault(args.shop, admin_token, "none")
    expected = "ROLLED_BACK" if rollback else "SUCCEEDED"
    out["result"] = "ok" if out["final_state"] == expected else "unexpected"
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shop", required=True)
    ap.add_argument("--sentinel", required=True)
    ap.add_argument("--scenarios", nargs="+", default=["S01", "S02", "S03", "S04", "S05", "S06", "S07"])
    ap.add_argument("--rollback", nargs="*", default=[], help="scenarios to run down the rollback path instead")
    ap.add_argument("--baseline-rounds", type=int, default=60)
    ap.add_argument("--fault-rounds", type=int, default=14)
    ap.add_argument("--out", default="campaign/results/e2e_recovery.jsonl")
    args = ap.parse_args()
    args.shop = args.shop.rstrip("/")
    need = ("SHOP_ADMIN_TOKEN", "SENTINEL_TOKEN", "SENTINEL_RESPONDER", "SENTINEL_APPROVER")
    if any(not os.environ.get(k) for k in need):
        sys.exit("set " + ", ".join(need))
    api = Api(args.sentinel, os.environ["SENTINEL_TOKEN"])
    responder, approver = api.login(os.environ["SENTINEL_RESPONDER"]), api.login(os.environ["SENTINEL_APPROVER"])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    jobs = [(k, False) for k in args.scenarios] + [(k, True) for k in args.rollback]
    for key, rollback in jobs:
        try:
            res = run_one(key, args, api, responder, approver, os.environ["SHOP_ADMIN_TOKEN"], rollback)
        except Exception as exc:  # noqa: BLE001 - one failed run must not lose the others
            res = {"scenario": key, "mode": "rollback" if rollback else "recover", "result": f"error: {exc}"}
        log(json.dumps(res))
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(res) + "\n")
        time.sleep(30)


if __name__ == "__main__":
    main()
