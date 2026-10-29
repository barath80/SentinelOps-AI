"""Feature extraction for the learned root-cause model, shared by training and serving.

Features are computed from telemetry alone: detect anomalies, take the incident candidate, then
measure signals over its routes. LOG_FEATURES come from request logs (model v1 used only these);
TRACE_FEATURES come from request traces and separate causes that look identical in logs (a slow
query, an exhausted connection pool, a dead cache and a saturated CPU all just look "slow"). When
nothing is traced every trace feature is 0 and `trace_coverage` says so. Training (notebooks/, training/) and the API's shadow model call
the same functions, so the model is served exactly the features it was trained on.
"""
from __future__ import annotations

import math
import statistics
from types import SimpleNamespace

from datetime import datetime

from ..adapters import otel_span, shop_json
from .detect import DetectionConfig, IncidentCandidate, Sample, detect, group, percentile, samples_from_rows
from .hypotheses import Features, build_hypotheses, compute_features, rank

TENANT = "00000000-0000-0000-0000-000000000001"

LOG_FEATURES = [
    "err_recent", "err_baseline", "err_delta", "log_p95_ratio", "latency_only", "version_changed",
    "exception_ratio", "fast_fail_ratio", "timeout_match_share", "timeouts_per_bad", "share_504",
    "log_volume_ratio", "n_routes_affected", "frac_routes_affected", "n_unaffected", "log_bad_median_ms",
    "other_routes_log_p95_ratio",
]
TRACE_FEATURES = [
    "trace_coverage", "pool_wait_share", "query_share", "cache_fail_share", "cpu_share",
    "payment_calls_per_request", "payment_hang_share", "retry_log_share",
]
FEATURES = LOG_FEATURES + TRACE_FEATURES


def rows(events: list[dict], now: datetime) -> list[SimpleNamespace]:
    """Raw events as row-like objects; span events (marked `_span`) go through the otel_span adapter."""
    out = []
    for e in events:
        n = otel_span(e["_span"], TENANT, now) if "_span" in e else shop_json(e, TENANT, now)
        out.append(SimpleNamespace(event_id=str(n.event_id), event_time=n.event_time, request_id=n.request_id,
                                   trace_id=n.trace_id, attributes=n.attributes, event_type=n.event_type))
    return out


def spans_by_trace(rs) -> dict[str, list]:
    out: dict[str, list] = {}
    for r in rs:
        if r.event_type == "trace" and getattr(r, "trace_id", None):
            out.setdefault(r.trace_id, []).append(r)
    return out


def _name(sp) -> str:
    return str((sp.attributes or {}).get("name", ""))


def _ms(sp) -> float:
    v = (sp.attributes or {}).get("duration_ms")
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def trace_features(bad: list[Sample], spans: dict[str, list], retried: set[str]) -> dict:
    """Trace-derived signals over the incident's failing/slow requests (all 0.0 without traces)."""
    out = dict.fromkeys(TRACE_FEATURES, 0.0)
    if not bad:
        return out
    kids_of = {s.event_id: [sp for sp in spans.get(s.trace_id or "", []) if (sp.attributes or {}).get("parent_span_id")] for s in bad}
    root_of = {s.event_id: next((sp for sp in spans.get(s.trace_id or "", []) if not (sp.attributes or {}).get("parent_span_id")), None)
               for s in bad}
    traced = [s for s in bad if kids_of[s.event_id] or root_of[s.event_id]]
    out["retry_log_share"] = sum(1 for s in bad if s.request_id in retried) / len(bad)
    if not traced:
        return out
    out["trace_coverage"] = len(traced) / len(bad)
    with_kids = [s for s in traced if kids_of[s.event_id]]
    share = lambda s, pick: min(1.0, sum(_ms(k) for k in kids_of[s.event_id] if pick(_name(k))) / max(s.duration_ms, 1.0))
    if with_kids:
        out["pool_wait_share"] = statistics.median(share(s, lambda n: n.startswith("db.pool")) for s in with_kids)
        out["query_share"] = statistics.median(share(s, lambda n: n.startswith("db.") and not n.startswith("db.pool")) for s in with_kids)
        out["cache_fail_share"] = sum(1 for s in with_kids if any(
            _name(k).startswith("cache.") and ((k.attributes or {}).get("status") == "error" or _ms(k) >= 200)
            for k in kids_of[s.event_id])) / len(with_kids)
        out["payment_hang_share"] = sum(1 for s in with_kids if any(
            _name(k).startswith("payment.") and _ms(k) >= 2000 for k in kids_of[s.event_id])) / len(with_kids)
        checkout = [s for s in with_kids if s.route == "/api/checkout"]
        if checkout:
            out["payment_calls_per_request"] = float(statistics.median(
                sum(1 for k in kids_of[s.event_id] if _name(k).startswith("payment.")) for s in checkout))
    cpu = [min(1.0, float(c) / max(s.duration_ms, 1.0)) for s in traced
           if root_of[s.event_id] is not None
           and isinstance(c := (root_of[s.event_id].attributes or {}).get("cpu_ms"), (int, float)) and not isinstance(c, bool)]
    if cpu:
        out["cpu_share"] = statistics.median(cpu)
    return out


def features_for_candidate(cand: IncidentCandidate, samples: list[Sample], f: Features,
                           timeouts: list[tuple[str, datetime, str | None]], spans: dict[str, list] | None = None) -> dict:
    """The model's feature vector for one incident candidate (all floats, keys == FEATURES)."""
    routes = set(cand.routes)
    recent = [s for s in samples if s.time >= cand.recent_start and s.time <= cand.as_of and s.route in routes]
    base = [s for s in samples if s.time < cand.recent_start and s.route in routes]
    bad = f.bad
    err = lambda xs: sum(s.is_error for s in xs) / len(xs) if xs else 0.0
    p95 = lambda xs: percentile([s.duration_ms for s in xs], 95) if xs else 0.0
    timeout_ids = {rid for _, _, rid in timeouts if rid}
    others = [s for s in samples if s.route not in routes and s.time <= cand.as_of]
    o_recent = [s for s in others if s.time >= cand.recent_start]
    o_base = [s for s in others if s.time < cand.recent_start]
    all_routes = {s.route for s in samples}
    return {
        "err_recent": err(recent),
        "err_baseline": err(base),
        "err_delta": err(recent) - err(base),
        "log_p95_ratio": math.log((p95(recent) + 1) / (p95(base) + 1)),
        "latency_only": float(f.latency_only),
        "version_changed": float(bool(f.base_versions) and bool(f.bad_versions) and not f.bad_versions <= f.base_versions),
        "exception_ratio": float(f.exception_ratio),
        "fast_fail_ratio": (sum(1 for s in bad if s.is_error and s.duration_ms < 50) / len(bad)) if bad else 0.0,
        "timeout_match_share": (sum(1 for s in bad if s.request_id in timeout_ids) / len(bad)) if bad else 0.0,
        "timeouts_per_bad": len(f.timeout_events) / max(1, len(bad)),
        "share_504": (sum(1 for s in bad if s.status == 504) / len(bad)) if bad else 0.0,
        "log_volume_ratio": math.log(f.volume_ratio) if f.volume_ratio else 0.0,
        "n_routes_affected": float(len(routes)),
        "frac_routes_affected": len(routes) / max(1, len(all_routes)),
        "n_unaffected": float(len(f.unaffected_routes)),
        "log_bad_median_ms": math.log1p(statistics.median([s.duration_ms for s in bad])) if bad else 0.0,
        "other_routes_log_p95_ratio": math.log((p95(o_recent) + 1) / (p95(o_base) + 1)) if o_recent and o_base else 0.0,
        **trace_features(bad, spans or {}, {rid for _, _, rid in f.retry_events if rid}),
    }


def extract(events: list[dict], now: datetime, cfg: DetectionConfig = DetectionConfig()) -> tuple[dict | None, str | None]:
    """Training helper: (features, rule_engine_answer) for raw shop events, or (None, None) when no
    incident is detected. rule_engine_answer is the rule engine's leading cause or "unknown"."""
    rs = rows(events, now)
    samples = samples_from_rows(rs)
    cands = group(detect(samples, now, cfg), now, cfg)
    if not cands:
        return None, None
    cand = max(cands, key=lambda c: len(c.anomalies))
    timeouts = [(r.event_id, r.event_time, r.request_id) for r in rs if (r.attributes or {}).get("message") == "payment_timeout"]
    retries = [(r.event_id, r.event_time, r.request_id) for r in rs if (r.attributes or {}).get("message") == "payment_retry"]
    f = compute_features(cand, samples, [(i, t) for i, t, _ in timeouts], retries)
    ranked, assessment = rank(build_hypotheses(cand, f))
    rule_answer = ranked[0].cause_key if assessment == "leading_hypothesis" else "unknown"
    return features_for_candidate(cand, samples, f, timeouts, spans_by_trace(rs)), rule_answer
