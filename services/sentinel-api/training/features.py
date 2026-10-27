"""Feature extraction for the root-cause classifier.

Features are computed by the SentinelOps detector from telemetry alone, exactly as in production:
detect anomalies, take the incident candidate, then measure signals over its routes. No label or
generator parameter is ever used here.
"""
from __future__ import annotations

import math
import statistics
from types import SimpleNamespace

from app.adapters import shop_json
from app.analysis.detect import DetectionConfig, detect, group, percentile, samples_from_rows
from app.analysis.hypotheses import build_hypotheses, compute_features, rank

from .generator import NOW

TENANT = "00000000-0000-0000-0000-000000000001"

FEATURES = [
    "err_recent", "err_baseline", "err_delta", "log_p95_ratio", "latency_only", "version_changed",
    "exception_ratio", "fast_fail_ratio", "timeout_match_share", "timeouts_per_bad", "share_504",
    "log_volume_ratio", "n_routes_affected", "frac_routes_affected", "n_unaffected", "log_bad_median_ms",
    "other_routes_log_p95_ratio",
]


def rows(events: list[dict]) -> list[SimpleNamespace]:
    out = []
    for e in events:
        n = shop_json(e, TENANT, NOW)
        out.append(SimpleNamespace(event_id=str(n.event_id), event_time=n.event_time, request_id=n.request_id,
                                   attributes=n.attributes, event_type=n.event_type))
    return out


def extract(events: list[dict], cfg: DetectionConfig = DetectionConfig()) -> tuple[dict | None, str | None]:
    """Returns (features, rule_engine_answer) or (None, None) when no incident is detected.

    rule_engine_answer is the current rule-based engine's leading cause, or "unknown" when it
    abstains, so the learned model can be compared with it on identical inputs."""
    rs = rows(events)
    samples = samples_from_rows(rs)
    cands = group(detect(samples, NOW, cfg), NOW, cfg)
    if not cands:
        return None, None
    cand = max(cands, key=lambda c: len(c.anomalies))
    timeouts = [(r.event_id, r.event_time, r.request_id) for r in rs if (r.attributes or {}).get("message") == "payment_timeout"]
    f = compute_features(cand, samples, [(i, t) for i, t, _ in timeouts])

    ranked, assessment = rank(build_hypotheses(cand, f))
    rule_answer = ranked[0].cause_key if assessment == "leading_hypothesis" else "unknown"

    routes = set(cand.routes)
    recent = [s for s in samples if s.time >= cand.recent_start and s.route in routes]
    base = [s for s in samples if s.time < cand.recent_start and s.route in routes]
    bad = f.bad
    err = lambda xs: sum(s.is_error for s in xs) / len(xs) if xs else 0.0
    p95 = lambda xs: percentile([s.duration_ms for s in xs], 95) if xs else 0.0
    timeout_ids = {rid for _, _, rid in timeouts if rid}
    others = [s for s in samples if s.route not in routes]
    o_recent = [s for s in others if s.time >= cand.recent_start]
    o_base = [s for s in others if s.time < cand.recent_start]
    all_routes = {s.route for s in samples}

    feats = {
        "err_recent": err(recent),
        "err_baseline": err(base),
        "err_delta": err(recent) - err(base),
        "log_p95_ratio": math.log((p95(recent) + 1) / (p95(base) + 1)),
        "latency_only": float(f.latency_only),
        "version_changed": float(bool(f.base_versions) and bool(f.bad_versions) and not f.bad_versions <= f.base_versions),
        "exception_ratio": f.exception_ratio,
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
    }
    return feats, rule_answer
