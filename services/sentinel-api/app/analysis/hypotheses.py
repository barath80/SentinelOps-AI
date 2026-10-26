"""Hypothesis generation, evidence ledger entries, and transparent ranking.

Rules produce candidate causes. Each rule attaches evidence that supports, contradicts, or is
missing, with a plain-language explanation built from the real measured numbers and the ids of
the stored events it came from. The score is a ranking heuristic, NOT a probability.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .detect import IncidentCandidate, Sample

SCORE_VERSION = "score-v1"
W_SUPPORT, W_TEMPORAL, W_DEPENDENCY, W_CONTRA, W_MISSING = 1.0, 0.5, 0.3, 1.2, 0.5
LEADING_MIN_SCORE = 1.0
LEADING_MIN_GAP = 0.5
FALSIFY_MIN_STRENGTH = 0.8  # diagnostics use >= 0.8 only for direct contradictions


@dataclass
class EvidenceItem:
    relation: str  # supports | contradicts | neutral | missing
    strength: float  # 0..1 ordinal strength of this one observation
    explanation: str
    source_refs: list[str] = field(default_factory=list)
    query_fingerprint: str = ""
    source: str = "rule"  # "rule" or "diagnostic:<test_id>"


@dataclass
class Hypothesis:
    cause_key: str
    title: str
    evidence: list[EvidenceItem]
    temporal: float
    dependency: float
    next_test_id: str
    score: float = 0.0
    falsified: bool = False
    status: str = "unlikely"
    breakdown: dict = field(default_factory=dict)


@dataclass
class Features:
    bad: list[Sample]
    recent: list[Sample]
    baseline: list[Sample]
    routes: list[str]
    error_dominant: bool
    latency_only: bool
    base_versions: set[str]
    bad_versions: set[str]
    exception_ratio: float
    timeout_events: list[tuple[str, datetime]]
    unaffected_routes: list[str]
    volume_ratio: float | None


def _fp(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:16]


def _ids(samples: list[Sample], n: int = 5) -> list[str]:
    return [s.event_id for s in samples[:n]]


def compute_features(c: IncidentCandidate, samples: list[Sample], timeout_events: list[tuple[str, datetime]]) -> Features:
    routes = set(c.routes)
    ours = [s for s in samples if s.route in routes and s.time <= c.as_of]
    recent = [s for s in ours if s.time >= c.recent_start]
    baseline = [s for s in ours if s.time < c.recent_start]
    error_anoms = [a for a in c.anomalies if a.kind == "errors"]
    bad = [s for s in recent if s.is_error] if error_anoms else [
        s for s in recent if s.time >= c.onset
    ]
    other = [s for s in samples if s.route not in routes and not s.route.startswith("/api/admin") and s.time <= c.as_of]
    unaffected = sorted(
        r for r in {s.route for s in other}
        if sum(1 for s in other if s.route == r and s.time >= c.recent_start) >= 3
        and not any(s.is_error for s in other if s.route == r and s.time >= c.recent_start)
    )
    base_span = max((c.recent_start - min((s.time for s in baseline), default=c.recent_start)).total_seconds(), 1.0)
    rec_rate = len([s for s in samples if s.time >= c.recent_start and s.time <= c.as_of]) / max(
        (c.as_of - c.recent_start).total_seconds(), 1.0
    )
    base_all = [s for s in samples if s.time < c.recent_start]
    base_rate = len(base_all) / base_span if len(base_all) >= 20 else None
    return Features(
        bad=bad, recent=recent, baseline=baseline, routes=sorted(routes),
        error_dominant=bool(error_anoms),
        latency_only=not error_anoms,
        base_versions={s.version for s in baseline if s.version},
        bad_versions={s.version for s in bad if s.version},
        exception_ratio=(sum(s.message == "unhandled_exception" for s in bad) / len(bad)) if bad else 0.0,
        timeout_events=[t for t in timeout_events if c.recent_start <= t[1] <= c.as_of],
        unaffected_routes=unaffected,
        volume_ratio=(rec_rate / base_rate) if base_rate else None,
    )


def build_hypotheses(c: IncidentCandidate, f: Features) -> list[Hypothesis]:
    where = ", ".join(f.routes)
    window = f"{c.recent_start.isoformat()}..{c.as_of.isoformat()}"
    out: list[Hypothesis] = []

    # 1. Release regression -------------------------------------------------------------
    ev: list[EvidenceItem] = []
    changed = bool(f.base_versions) and bool(f.bad_versions) and not f.bad_versions <= f.base_versions
    if changed:
        ev.append(EvidenceItem("supports", 0.8,
            f"Release label changed from {sorted(f.base_versions)} (baseline) to {sorted(f.bad_versions)} on the failing requests.",
            _ids(f.bad), _fp("version-change", where, window)))
    elif f.base_versions and f.bad_versions:
        ev.append(EvidenceItem("contradicts", 0.7,
            f"Failing requests carry the same release label as the baseline ({sorted(f.bad_versions)}), so no release change is visible.",
            _ids(f.bad), _fp("version-same", where, window)))
    if f.error_dominant and f.exception_ratio >= 0.8:
        ev.append(EvidenceItem("supports", 0.5,
            f"{f.exception_ratio:.0%} of failing requests ended in unhandled exceptions (code-level failures), not upstream errors.",
            _ids([s for s in f.bad if s.message == 'unhandled_exception']), _fp("exceptions", where, window)))
    if f.unaffected_routes:
        ev.append(EvidenceItem("supports", 0.3,
            f"Failures are confined to {where}; {', '.join(f.unaffected_routes)} stayed healthy, consistent with a route-local code change.",
            [], _fp("route-local", where, window)))
    ev.append(EvidenceItem("missing", 0.4,
        "No deployment-event feed is ingested: release changes are inferred from version labels on request logs, not from a deploy record.",
        [], _fp("missing-deploy-feed")))
    out.append(Hypothesis("release_regression", "A newly released version introduced a defect", ev,
        temporal=1.0 if changed else 0.0, dependency=1.0, next_test_id="compare_error_rate_before_after_release"))

    # 2. Payment provider timeouts --------------------------------------------------------
    ev = []
    timeouts_in_bad = [s for s in f.bad if s.status == 504 and s.duration_ms >= 2500]
    share = len(timeouts_in_bad) / len(f.bad) if f.bad else 0.0
    if f.timeout_events:
        ev.append(EvidenceItem("supports", 0.9,
            f"{len(f.timeout_events)} payment_timeout events were logged in the incident window.",
            [e for e, _ in f.timeout_events[:5]], _fp("payment-timeouts", window)))
    if share >= 0.6:
        ev.append(EvidenceItem("supports", 0.6,
            f"{share:.0%} of failing requests were 504s lasting about {min(s.duration_ms for s in timeouts_in_bad):.0f} ms or more, a timeout signature.",
            _ids(timeouts_in_bad), _fp("504-share", where, window)))
    if f.error_dominant and not f.timeout_events:
        ev.append(EvidenceItem("contradicts", 0.8,
            "Errors occurred but no payment_timeout events were logged.", _ids(f.bad), _fp("no-timeouts", window)))
    ev.append(EvidenceItem("missing", 0.1,
        "The payment provider's own status feed was not checked.", [], _fp("missing-provider-status")))
    first_to = min((t for _, t in f.timeout_events), default=None)
    out.append(Hypothesis("payment_provider_timeout", "The payment provider is timing out", ev,
        temporal=1.0 if first_to and abs((first_to - c.onset).total_seconds()) <= 60 else 0.0,
        dependency=1.0 if "/api/checkout" in f.routes else 0.3,
        next_test_id="inspect_payment_provider_status_and_spans"))

    # 3. Slow dependency (e.g. database query) --------------------------------------------
    ev = []
    rec_err = sum(s.is_error for s in f.recent) / len(f.recent) if f.recent else 0.0
    slow_anom = next((a for a in c.anomalies if a.kind == "latency"), None)
    if f.latency_only and slow_anom and rec_err < 0.05:
        ev.append(EvidenceItem("supports", 0.7,
            f"Latency on {where} rose (p95 {slow_anom.baseline_p95_ms:.0f} ms to {slow_anom.recent_p95_ms:.0f} ms) while the error rate stayed {rec_err:.1%}: requests are slow but succeeding.",
            slow_anom.bad_event_ids[:5], _fp("slow-not-failing", where, window)))
        if f.unaffected_routes:
            ev.append(EvidenceItem("supports", 0.2,
                f"Only {where} is slow; {', '.join(f.unaffected_routes)} unaffected, suggesting a dependency used by this route only.",
                [], _fp("slow-route-local", where, window)))
    elif f.error_dominant:
        ev.append(EvidenceItem("contradicts", 0.8,
            f"The dominant symptom is errors ({rec_err:.0%} of requests), not slowness alone.", _ids(f.bad), _fp("errors-dominate", window)))
    ev.append(EvidenceItem("missing", 0.5,
        "No database or dependency metrics (query duration, pool wait, connection counts) are ingested, so a slow dependency cannot be confirmed from request logs alone.",
        [], _fp("missing-db-metrics")))
    out.append(Hypothesis("slow_dependency", "A slow dependency (for example a database query) is adding latency", ev,
        temporal=0.5 if slow_anom else 0.0, dependency=0.5, next_test_id="inspect_db_pool_wait_and_query_duration"))

    # 4. Traffic surge ----------------------------------------------------------------------
    ev = []
    if f.volume_ratio is None:
        ev.append(EvidenceItem("missing", 0.3, "Not enough baseline traffic to compare request volume.", [], _fp("missing-baseline-volume")))
    elif f.volume_ratio >= 3:
        ev.append(EvidenceItem("supports", 0.8, f"Request rate is {f.volume_ratio:.1f}x the baseline rate.", [], _fp("volume-up", window)))
    elif f.volume_ratio <= 1.5:
        ev.append(EvidenceItem("contradicts", 0.6, f"Request rate is {f.volume_ratio:.1f}x baseline: no surge in traffic.", [], _fp("volume-flat", window)))
    out.append(Hypothesis("traffic_surge", "A traffic surge overloaded the service", ev,
        temporal=1.0 if f.volume_ratio and f.volume_ratio >= 3 else 0.0, dependency=0.5,
        next_test_id="compare_request_rate_to_baseline"))
    return out


def rank(hypotheses: list[Hypothesis]) -> tuple[list[Hypothesis], str]:
    """Score, order, and label. Returns (ranked, assessment) where assessment is
    'leading_hypothesis' or 'inconclusive' (abstain rather than force a winner)."""
    for h in hypotheses:
        support = min(sum(e.strength for e in h.evidence if e.relation == "supports"), 2.0)
        contra = min(sum(e.strength for e in h.evidence if e.relation == "contradicts"), 2.0)
        missing = min(sum(e.strength for e in h.evidence if e.relation == "missing"), 1.0)
        # Timing and topology only add credit when something actually supports the hypothesis;
        # otherwise a cause with zero evidence could outrank honest uncertainty.
        temporal = h.temporal if support > 0 else 0.0
        dependency = h.dependency if support > 0 else 0.0
        h.score = round(W_SUPPORT * support + W_TEMPORAL * temporal + W_DEPENDENCY * dependency
                        - W_CONTRA * contra - W_MISSING * missing, 3)
        h.breakdown = {"supporting": support, "temporal": temporal, "dependency": dependency,
                       "raw_temporal": h.temporal, "raw_dependency": h.dependency,
                       "contradicting": contra, "missing_penalty": missing, "version": SCORE_VERSION}
    # A diagnostic that directly contradicts a hypothesis (strength >= 0.8) falsifies it:
    # it can no longer lead, whatever the rest of its evidence says.
    for h in hypotheses:
        h.falsified = any(e.relation == "contradicts" and e.source.startswith("diagnostic") and e.strength >= FALSIFY_MIN_STRENGTH
                          for e in h.evidence)
    ranked = sorted(hypotheses, key=lambda h: (not h.falsified, h.score), reverse=True)
    live = [h for h in ranked if not h.falsified]
    top = live[0] if live else None
    gap = (top.score - live[1].score if len(live) > 1 else top.score) if top else 0.0
    if top and top.score >= LEADING_MIN_SCORE and gap >= LEADING_MIN_GAP:
        assessment, top.status = "leading_hypothesis", "leading"
    else:
        assessment = "inconclusive"
        if top:
            top.status = "uncertain"
    for h in ranked:
        if h.falsified:
            h.status = "falsified"
        elif h is not top:
            h.status = "alternative" if h.score >= 0 else "unlikely"
            if assessment == "inconclusive" and len(live) > 1 and h is live[1] and gap < LEADING_MIN_GAP:
                h.status = "uncertain"
    return ranked, assessment
