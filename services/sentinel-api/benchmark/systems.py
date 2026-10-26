"""The systems under comparison. Each receives ONLY the telemetry events (and the as-of time).

  alert_correlator  naive baseline: threshold alerts + "blame the latest change"
  llm_only          baseline: an LLM reads a summary of the same telemetry (needs ANTHROPIC_API_KEY)
  sentinel          SentinelOps analysis, no falsification step
  sentinel_falsify  SentinelOps analysis + the falsification/investigation loop
"""
from __future__ import annotations

import json
import os
import statistics
import tempfile
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
from sqlalchemy import select

from app.adapters import shop_json
from app.analysis.detect import Sample, percentile, samples_from_rows
from app.analysis.diagnostics import investigate
from app.analysis.service import analyze
from app.db import EventRow, HypothesisRow, IncidentRow, make_session_factory
from app.recovery import slo
from app.recovery.contracts import default_slos
from app.recovery.policy import RECOMMENDED_ACTION, evaluate as policy_evaluate

from .scenarios import NOW, window

TENANT = "00000000-0000-0000-0000-000000000001"
CAUSES = ["release_regression", "payment_provider_timeout", "slow_dependency", "traffic_surge"]


@dataclass
class SystemResult:
    detected: bool = False
    cause: str | None = None  # None = abstained (or nothing detected)
    causes: list = field(default_factory=list)  # every cause the system claims (multi-cause aware)
    unexplained: int = 0  # symptoms the system says it could not attribute
    action: str | None = None
    claims_success: bool | None = None  # None = made no claim (e.g. verification inconclusive/pending)
    verification: str | None = None
    tests_run: int = 0
    elapsed_ms: int = 0
    llm_tokens: int = 0
    notes: dict = field(default_factory=dict)


def rows_from_events(events: list[dict]) -> list[SimpleNamespace]:
    """Normalize raw shop lines exactly as the ingest API would, as row-like objects."""
    out = []
    for e in events:
        n = shop_json(e, TENANT, NOW)
        out.append(SimpleNamespace(event_id=str(n.event_id), event_time=n.event_time, request_id=n.request_id,
                                   attributes=n.attributes, event_type=n.event_type))
    return out


def _safe_action(cause: str | None) -> str | None:
    action = RECOMMENDED_ACTION.get(cause) if cause else None
    return action if action and policy_evaluate(action, "demo").allowed else None


def _verify_with_slo(incident_defaults, post_events: list[dict]) -> str:
    success, guards, _ = incident_defaults
    start, end = window()
    samples = samples_from_rows(rows_from_events(post_events))
    outcome, _, _ = slo.evaluate(success, guards, samples, start, end, max_gap_seconds=30)
    return outcome


# ---- baseline 1: naive alert correlator --------------------------------------------------------

def alert_correlator(events: list[dict], post_events_for) -> SystemResult:
    t0 = time.perf_counter()
    samples = samples_from_rows(rows_from_events(events))
    cut = NOW - timedelta(seconds=120)
    alerts, versions_before, versions_after = [], set(), set()
    for route in {s.route for s in samples}:
        base = [s for s in samples if s.route == route and s.time < cut]
        rec = [s for s in samples if s.route == route and s.time >= cut]
        if len(rec) < 5 or len(base) < 10:
            continue
        err = sum(s.is_error for s in rec) / len(rec)
        p95, base_p95 = percentile([s.duration_ms for s in rec], 95), percentile([s.duration_ms for s in base], 95)
        if err > 0.05 or (p95 > 3 * base_p95 and p95 - base_p95 > 300):
            alerts.append((route, "errors" if err > 0.05 else "latency"))
            versions_before |= {s.version for s in base if s.version}
            versions_after |= {s.version for s in rec if s.version}
    res = SystemResult(detected=bool(alerts), notes={"alerts": alerts})
    if alerts:
        if versions_after - versions_before:  # "the latest change is the cause"
            res.cause = "release_regression"
        elif all(kind == "latency" for _, kind in alerts):
            res.cause = "slow_dependency"
        res.action = _safe_action(res.cause)
        if res.action:
            res.claims_success = True  # no verification step: executing the action is treated as the fix
    res.causes = [res.cause] if res.cause else []
    res.elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return res


# ---- baseline 2: LLM only -----------------------------------------------------------------------

def summarize_for_llm(events: list[dict]) -> str:
    """A compact summary of the same telemetry the other systems see. No ground truth."""
    samples = samples_from_rows(rows_from_events(events))
    cut = NOW - timedelta(seconds=120)
    lines = []
    for route in sorted({s.route for s in samples}):
        for label, part in (("earlier", [s for s in samples if s.route == route and s.time < cut]),
                            ("last 2 min", [s for s in samples if s.route == route and s.time >= cut])):
            if not part:
                continue
            lines.append(f"{route} [{label}]: n={len(part)} error_rate={sum(s.is_error for s in part) / len(part):.0%} "
                         f"p95_ms={percentile([s.duration_ms for s in part], 95):.0f} "
                         f"release={sorted({s.version for s in part if s.version})}")
    rows = rows_from_events(events)
    timeouts = sum(1 for r in rows if r.attributes.get("message") == "payment_timeout")
    exceptions = sum(1 for s in samples if s.message == "unhandled_exception")
    lines.append(f"payment_timeout log lines: {timeouts}; unhandled exceptions: {exceptions}")
    return "\n".join(lines)


def llm_only(events: list[dict], post_events_for, *, transport=None) -> SystemResult | None:
    """Returns None when no API key is configured (the benchmark then reports the system as not run)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key and transport is None:
        return None
    t0 = time.perf_counter()
    prompt = ("You are an SRE assistant. Below is telemetry from an online shop. Decide the most likely root cause, "
              f"or say unknown if the evidence does not support one.\nAllowed causes: {CAUSES + ['unknown']}\n\n"
              + summarize_for_llm(events)
              + '\n\nAnswer with JSON only: {"cause": "<one of the allowed causes>", "incident": true|false}')
    with httpx.Client(transport=transport, timeout=60) as client:
        r = client.post("https://api.anthropic.com/v1/messages",
                        headers={"x-api-key": key or "test", "anthropic-version": "2023-06-01"},
                        json={"model": os.environ.get("LLM_MODEL", "claude-haiku-5-5"), "max_tokens": 200,
                              "temperature": 0, "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    body = r.json()
    text = "".join(b.get("text", "") for b in body.get("content", []))
    try:
        data = json.loads(text[text.index("{"): text.rindex("}") + 1])
    except ValueError:
        data = {}
    usage = body.get("usage", {})
    cause = data.get("cause") if data.get("cause") in CAUSES else None
    res = SystemResult(detected=bool(data.get("incident", cause is not None)), cause=cause,
                       llm_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
    res.action = _safe_action(cause)
    res.claims_success = True if res.action else None  # no verification step
    res.causes = [cause] if cause else []
    res.elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return res


# ---- SentinelOps ---------------------------------------------------------------------------------

def sentinel(events: list[dict], post_events_for, *, falsify: bool) -> SystemResult:
    t0 = time.perf_counter()
    tmp = Path(tempfile.mkdtemp(prefix="bench-")) / "b.db"
    sessions = make_session_factory(f"sqlite:///{tmp}")
    try:
        with sessions.begin() as s:
            for e in events:
                n = shop_json(e, TENANT, NOW)
                s.merge(EventRow(tenant_id=TENANT, event_id=str(n.event_id), environment=n.environment,
                                 service_name=n.service_name, event_type=n.event_type, event_time=n.event_time,
                                 ingest_time=n.ingest_time, trace_id=n.trace_id, request_id=n.request_id,
                                 severity=n.severity, source_ref=n.source_ref, attributes=n.attributes,
                                 schema_version=n.schema_version))
        with sessions.begin() as s:
            ids = analyze(s, TENANT, NOW)
        res = SystemResult(detected=bool(ids))
        if ids:
            with sessions.begin() as s:
                inc = s.get(IncidentRow, ids[0])
                if falsify:
                    report = investigate(s, inc, budget=3)
                    res.tests_run = len(report["steps"])
                    res.notes["stop_reason"] = report["stop_reason"]
                leader = s.scalars(select(HypothesisRow).where(HypothesisRow.incident_id == inc.id)
                                   .order_by(HypothesisRow.score.desc())).first()
                if inc.assessment == "leading_hypothesis" and leader and leader.status == "leading":
                    res.cause = leader.cause_key
                res.causes = list(inc.summary.get("causes", []))
                res.unexplained = len(inc.summary.get("unexplained_symptoms", []))
                res.notes["attribution"] = inc.summary.get("attribution")
                res.notes["assessment"] = inc.assessment
                res.action = _safe_action(res.cause)
                if res.action:
                    # Verification from measured post-action telemetry only.
                    outcome = _verify_with_slo(default_slos(inc), post_events_for(res.action))
                    res.verification = outcome
                    res.claims_success = True if outcome == "pass" else (False if outcome == "fail" else None)
        res.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return res
    finally:
        sessions.kw["bind"].dispose()


SYSTEMS = {
    "alert_correlator": lambda ev, post: alert_correlator(ev, post),
    "llm_only": lambda ev, post: llm_only(ev, post),
    "sentinel": lambda ev, post: sentinel(ev, post, falsify=False),
    "sentinel_falsify": lambda ev, post: sentinel(ev, post, falsify=True),
}
