"""Recovery rehearsal: replay the incident's recorded telemetry with the action's modelled effect.

Before anyone approves an action, this asks: "if the action did what it is meant to do, would the
contract's success conditions have held over the incident window?" Each action has an explicit,
deliberately narrow effect model. Where the recorded telemetry cannot show the effect (for example
no request is still on the previous release, so nothing shows how that release behaves now) the
answer is `inconclusive`, never an optimistic guess.

The result is SIMULATION EVIDENCE. It is not a sandbox copy of production, it never touches any
system, and a passing rehearsal is not a recovery: only post-action verification decides that.
Its use is the opposite direction: a rehearsal that FAILS shows the action cannot fix what the
telemetry shows, which is the case where acting would be an incorrect intervention.
"""
from __future__ import annotations

import statistics
from dataclasses import replace
from datetime import datetime

from sqlalchemy.orm import Session

from ..analysis.diagnostics import Context, _child_spans, _span_ms, load_context
from ..analysis.detect import Sample
from ..db import IncidentRow
from . import slo

MODEL_VERSION = "rehearsal-v1"
LABEL = ("Simulation evidence: recorded telemetry replayed with the action's modelled effect. "
         "Not a sandbox copy, not production, and not proof of recovery.")
# The incident window is short, so rehearsal accepts fewer samples than verification does. It is
# advisory: a pass here never replaces the full verification window after the action.
MIN_SAMPLES = {"error_rate": 5, "p95_latency_ms": 10}


def _affected(ctx: Context, s: Sample) -> bool:
    return s.route in ctx.candidate.routes and s.time >= ctx.candidate.recent_start


def _route_baseline_ms(ctx: Context, route: str) -> float | None:
    xs = [s.duration_ms for s in ctx.features.baseline if s.route == route and not s.is_error]
    return statistics.median(xs) if xs else None


def _rollback_release(ctx: Context) -> tuple[list[Sample] | None, str, dict]:
    """Requests still on a previous release, in the same window, show how a rollback would behave."""
    old = ctx.features.base_versions
    affected = [s for s in ctx.samples if _affected(ctx, s)]
    kept = [s for s in affected if s.version in old]
    details = {"previous_releases": sorted(old), "affected_requests": len(affected), "on_previous_release": len(kept)}
    if not old or not kept:
        return None, ("No request in the incident window ran on the previous release, so recorded telemetry "
                      "cannot show how that release behaves now."), details
    # Every affected request is assumed to behave like the previous-release requests seen in the window.
    others = [s for s in ctx.samples if not _affected(ctx, s)]
    return others + kept, f"replayed {len(kept)} same-window requests on {sorted(old)} as the post-rollback traffic", details


def _restore_payment(ctx: Context) -> tuple[list[Sample] | None, str, dict]:
    """Requests that failed on a payment timeout succeed; every other failure is left as it was."""
    timed_out = {rid for _, _, rid in ctx.timeouts if rid}
    out, changed = [], 0
    for s in ctx.samples:
        spans = [sp for sp in _child_spans(ctx, s) if str((sp.attributes or {}).get("name", "")).startswith("payment.")]
        hit = s.request_id in timed_out or any(
            (sp.attributes or {}).get("status") == "error" or _span_ms(sp) >= 2000 for sp in spans)
        if _affected(ctx, s) and s.is_error and hit:
            base = _route_baseline_ms(ctx, s.route)
            if spans:  # remove the time spent waiting on the provider
                duration = max(1.0, s.duration_ms - sum(_span_ms(sp) for sp in spans))
            elif base is not None:
                duration = base
            else:
                duration = s.duration_ms
            out.append(replace(s, status=201, duration_ms=duration))
            changed += 1
        else:
            out.append(s)
    failing = [s for s in ctx.samples if _affected(ctx, s) and s.is_error]
    details = {"requests_changed": changed, "failing_requests": len(failing)}
    if not changed:
        # Linkage was measurable (timeouts were logged, or failing requests were traced) and found
        # none: restoring the provider would leave every failure as it is.
        if ctx.timeouts or any(_child_spans(ctx, s) for s in failing):
            return out, "no failing request is linked to a payment timeout: restoring the provider changes nothing", details
        return None, "No payment timeouts were logged and failing requests are not traced: the effect cannot be estimated.", details
    return out, f"{changed} failing requests linked to a payment timeout replayed as successful", details


def _remove_time(ctx: Context, spent_ms, what: str) -> tuple[list[Sample] | None, str, dict]:
    """Time measured by `spent_ms(sample)` above its baseline median is removed from affected requests.
    `spent_ms` returns None when the request carries no such measurement (no traces, no attribute)."""
    base = [v for v in (spent_ms(s) for s in ctx.features.baseline) if v is not None]
    normal = statistics.median(base) if base else 0.0
    out, changed, measured = [], 0, 0
    for s in ctx.samples:
        spent = spent_ms(s) if _affected(ctx, s) else None
        measured += spent is not None
        if spent is not None and spent > normal:
            out.append(replace(s, duration_ms=max(1.0, s.duration_ms - (spent - normal))))
            changed += 1
        else:
            out.append(s)
    details = {"requests_changed": changed, "requests_measured": measured, "baseline_ms": round(normal, 1),
               "baseline_measured": len(base)}
    if not measured:
        return None, f"No affected request measures {what}, so the action's effect cannot be estimated.", details
    if not changed:  # measured, and there is nothing for the action to remove: it would change nothing
        return out, f"{measured} affected requests measure {what} and none is above the {normal:.0f} ms baseline: no effect", details
    return out, f"{what} above the {normal:.0f} ms baseline removed from {changed} requests", details


def _span_time(ctx: Context, match):
    def spent(s: Sample) -> float | None:
        kids = [k for k in _child_spans(ctx, s) if match(str((k.attributes or {}).get("name", "")))]
        return sum(_span_ms(k) for k in kids) if kids else None
    return spent


def _cpu_time(ctx: Context):
    def spent(s: Sample) -> float | None:
        root = next((sp for sp in ctx.spans.get(s.trace_id or "", []) if not (sp.attributes or {}).get("parent_span_id")), None)
        cpu = (root.attributes or {}).get("cpu_ms") if root else None
        return float(cpu) if isinstance(cpu, (int, float)) and not isinstance(cpu, bool) else None
    return spent


EFFECTS = {
    "rollback_release": _rollback_release,
    "restore_payment_simulator": _restore_payment,
    "apply_query_fix": lambda ctx: _remove_time(
        ctx, _span_time(ctx, lambda n: n.startswith("db.") and not n.startswith("db.pool")), "time in database query spans"),
    "recycle_db_pool": lambda ctx: _remove_time(ctx, _span_time(ctx, lambda n: n.startswith("db.pool")), "time waiting for a database connection"),
    "restore_cache": lambda ctx: _remove_time(ctx, _span_time(ctx, lambda n: n.startswith("cache.")), "time in cache calls"),
    "scale_out": lambda ctx: _remove_time(ctx, _cpu_time(ctx), "on-CPU time"),
    # enable_retry_backoff has no model: fewer retries change both latency and the failure rate in
    # ways recorded telemetry cannot show, so its rehearsal is always inconclusive.
}


def rehearse(session: Session, incident: IncidentRow, action: str, contract: dict) -> dict:
    """Returns {'outcome': pass|fail|inconclusive, 'reason', 'details'}. Reads stored events only."""
    base = {"model_version": MODEL_VERSION, "label": LABEL, "action": action}
    model = EFFECTS.get(action)
    if model is None:
        return {**base, "outcome": "inconclusive", "reason": f"no effect model for {action}", "details": {}}
    ctx = load_context(session, incident)
    if ctx is None:
        return {**base, "outcome": "inconclusive", "reason": "the incident's anomaly is no longer reproducible from stored events",
                "details": {}}
    replayed, how, details = model(ctx)
    if replayed is None:
        return {**base, "outcome": "inconclusive", "reason": how, "details": details}
    start: datetime = ctx.candidate.recent_start
    end: datetime = ctx.candidate.as_of
    adjust = lambda p: slo.Predicate(**{**p, "min_samples": min(p.get("min_samples", 5), MIN_SAMPLES[p["sli"]])})
    success = [adjust(p) for p in contract["success_conditions"]]
    guards = [adjust(p) for p in contract["safety_guardrails"]]
    outcome, reason, predicates = slo.evaluate(success, guards, replayed, start, end, contract["max_gap_seconds"])
    return {**base, "outcome": outcome, "reason": f"{reason} (replay: {how})",
            "details": {**details, "window": {"start": start.isoformat(), "end": end.isoformat()}, "predicates": predicates}}
