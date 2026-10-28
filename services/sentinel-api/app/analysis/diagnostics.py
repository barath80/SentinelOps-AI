"""Read-only diagnostic tests that try to FALSIFY a hypothesis, and the investigation loop.

Each test is an allow-listed function over already-stored events. Nothing here can change
any system: no shell, no arbitrary query, no network. A test's result becomes ledger evidence
(supports / contradicts) and the incident is re-ranked; earlier scores stay in `score_history`.
"""
from __future__ import annotations

import hashlib
import statistics
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import DiagnosticRunRow, EventRow, EvidenceRow, HypothesisRow, IncidentRow
from .detect import DetectionConfig, IncidentCandidate, Sample, detect, group, samples_from_rows
from .hypotheses import SCORE_VERSION, EvidenceItem, Features, Hypothesis, compute_features, rank

LOOKBACK_SECONDS = 900


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class Context:
    candidate: IncidentCandidate
    features: Features
    samples: list[Sample]
    timeouts: list[tuple[str, datetime, str | None]]  # (event_id, time, request_id)
    metrics: list[EventRow]
    spans: dict[str, list[EventRow]] = field(default_factory=dict)  # trace_id -> span events


def _child_spans(ctx: "Context", s: Sample) -> list[EventRow]:
    """The child spans (anything but the root) recorded for one request's trace."""
    return [sp for sp in ctx.spans.get(s.trace_id or "", []) if (sp.attributes or {}).get("parent_span_id")]


def _span_ms(sp: EventRow) -> float:
    v = (sp.attributes or {}).get("duration_ms")
    return float(v) if isinstance(v, (int, float)) else 0.0


def _span_name(sp: EventRow) -> str:
    return str((sp.attributes or {}).get("name", ""))


def _root_span(ctx: "Context", s: Sample) -> EventRow | None:
    return next((sp for sp in ctx.spans.get(s.trace_id or "", []) if not (sp.attributes or {}).get("parent_span_id")), None)


def _is_query_span(sp: EventRow) -> bool:
    # "db.query ..." spans time the query itself; "db.pool.acquire" is waiting for a connection.
    return _span_name(sp).startswith("db.") and not _span_name(sp).startswith("db.pool")


def _share_in_spans(ctx: "Context", pick) -> tuple[list[float], list[tuple[Sample, list[EventRow]]]]:
    """For each traced failing/slow request: the share of its duration spent in spans chosen by `pick`."""
    traced = [(s, kids) for s, kids in ((s, _child_spans(ctx, s)) for s in ctx.features.bad) if kids]
    shares = [min(1.0, sum(_span_ms(k) for k in kids if pick(k)) / max(s.duration_ms, 1.0)) for s, kids in traced]
    return shares, traced


@dataclass
class DiagnosticResult:
    outcome: str  # supports | contradicts | inconclusive | no_data
    strength: float
    explanation: str
    details: dict = field(default_factory=dict)
    source_refs: list[str] = field(default_factory=list)


def _is_bad(s: Sample, slow_ms: float) -> bool:
    return s.is_error or s.duration_ms >= slow_ms


def _slow_threshold(ctx: Context) -> float:
    p95s = [a.baseline_p95_ms for a in ctx.candidate.anomalies if a.baseline_p95_ms is not None]
    base = max(p95s) if p95s else 0.0
    return max(base * 2, base + 200, 200.0)


def compare_error_rate_before_after_release(ctx: Context) -> DiagnosticResult:
    """If a release caused this, the old version should be healthy and the new one failing."""
    slow = _slow_threshold(ctx)
    recent, base = ctx.features.recent, ctx.features.baseline
    if not base or not recent:
        return DiagnosticResult("no_data", 0.0, "No baseline or recent requests to compare across a release.")
    by_ver: dict[str, list[Sample]] = {}
    for s in recent:
        by_ver.setdefault(s.version or "unknown", []).append(s)
    rate = lambda xs: sum(_is_bad(s, slow) for s in xs) / len(xs)
    base_rate = rate(base)
    details = {"baseline_bad_rate": round(base_rate, 3),
               "recent_bad_rate_by_version": {v: round(rate(xs), 3) for v, xs in by_ver.items()}}
    base_versions = {s.version for s in base if s.version}
    new_versions = [v for v in by_ver if v not in base_versions]
    old_versions = [v for v in by_ver if v in base_versions]
    refs = [s.event_id for s in ctx.features.bad[:5]]
    if new_versions and old_versions:  # both versions served traffic in the same window
        new_rate = max(rate(by_ver[v]) for v in new_versions)
        old_rate = max(rate(by_ver[v]) for v in old_versions)
        if old_rate >= 0.5 * new_rate and old_rate > 0.1:
            return DiagnosticResult("contradicts", 0.9,
                f"The old release is failing too ({old_rate:.0%} vs {new_rate:.0%} on the new one), so the new release is not the distinguishing factor.", details, refs)
        return DiagnosticResult("supports", 0.9,
            f"Only the new release fails ({new_rate:.0%}); the old release in the same window is healthy ({old_rate:.0%}).", details, refs)
    if new_versions:
        if base_rate >= 0.5 * rate(recent) and base_rate > 0.1:
            return DiagnosticResult("contradicts", 0.9,
                f"The same failure rate existed before the release change ({base_rate:.0%} baseline vs {rate(recent):.0%} now).", details, refs)
        # Without old-release traffic this only restates that the change and the onset coincide. For a
        # pure slowdown that is weak evidence (release defects usually show up as errors).
        return DiagnosticResult("supports", 0.4 if ctx.features.latency_only else 0.6,
            f"Healthy before the release change ({base_rate:.0%} bad), failing after ({rate(recent):.0%}). No old-release traffic remains for a side-by-side comparison.", details, refs)
    return DiagnosticResult("contradicts", 0.8,
        f"No release change is visible: failures occur on the same release label as the healthy baseline ({sorted(base_versions)}).", details, refs)


def inspect_payment_provider_status_and_spans(ctx: Context) -> DiagnosticResult:
    """If the provider is the cause, failing requests should be the ones that logged a timeout."""
    bad = ctx.features.bad
    if not bad:
        return DiagnosticResult("no_data", 0.0, "No failing requests to match against payment timeouts.")
    timeout_requests = {rid for _, _, rid in ctx.timeouts if rid}

    def payment_span_failed(s: Sample) -> bool:
        # A timeout signature: one provider call that hung for 2 s or more. A provider that fails
        # fast (and is retried) is a different failure, tested by inspect_retry_amplification.
        return any(_span_name(sp).startswith("payment.") and _span_ms(sp) >= 2000 for sp in _child_spans(ctx, s))

    # Either signal counts: a payment_timeout log line, or a hung payment span in the trace.
    matched = [s for s in bad if s.request_id in timeout_requests or payment_span_failed(s)]
    share = len(matched) / len(bad)
    details = {"failing_requests": len(bad), "with_payment_timeout": len(matched),
               "matched_by_log": sum(1 for s in bad if s.request_id in timeout_requests),
               "matched_by_trace": sum(1 for s in bad if payment_span_failed(s)),
               "provider_status_feed": "not checked (no external feed configured)"}
    refs = [s.event_id for s in matched[:5]]
    if share >= 0.8:
        return DiagnosticResult("supports", 0.9, f"{share:.0%} of failing requests logged a payment timeout.", details, refs)
    if share <= 0.2:
        return DiagnosticResult("contradicts", 0.8,
            f"Only {share:.0%} of failing requests logged a payment timeout; most failures have another cause.", details, [s.event_id for s in bad[:5]])
    return DiagnosticResult("inconclusive", 0.0, f"{share:.0%} of failing requests logged a payment timeout: neither clearly explained nor ruled out.", details, refs)


def _db_share_from_traces(ctx: Context) -> DiagnosticResult | None:
    """If the slow requests were traced: does time inside database spans explain the slowness?"""
    shares, traced = _share_in_spans(ctx, _is_query_span)
    if len(traced) < 3:
        return None
    med = statistics.median(shares)
    details = {"traced_slow_requests": len(traced), "median_share_in_db_spans": round(med, 3)}
    refs = [k.event_id for _, kids in traced[:3] for k in kids[:2]]
    if med >= 0.5:
        return DiagnosticResult("supports", 0.9, f"Database query spans account for {med:.0%} of the slow requests' time (median over {len(traced)} traces).", details, refs)
    if med <= 0.2:
        return DiagnosticResult("contradicts", 0.8, f"Only {med:.0%} of the slow requests' time is spent in database queries (median over {len(traced)} traces); the time goes elsewhere.", details, refs)
    return DiagnosticResult("inconclusive", 0.0, f"Database spans account for {med:.0%} of the slow requests' time: partly but not clearly the cause.", details, refs)


def inspect_db_pool_wait_and_query_duration(ctx: Context) -> DiagnosticResult:
    """Database metrics (db_query_duration_ms / db_pool_wait_ms) if ingested, otherwise traces."""
    wanted = ("db_query_duration_ms", "db_pool_wait_ms")
    rows = [r for r in ctx.metrics if (r.attributes or {}).get("metric_name") in wanted
            and isinstance((r.attributes or {}).get("value"), (int, float))]
    if not rows:
        from_traces = _db_share_from_traces(ctx)
        if from_traces is not None:
            return from_traces
        return DiagnosticResult("no_data", 0.0,
            "No database metrics (query duration, pool wait) and no request traces have been ingested, so this cannot be tested.",
            {"looked_for": list(wanted) + ["db.* spans in request traces"]})
    cut = ctx.candidate.recent_start
    before = [r.attributes["value"] for r in rows if _aware(r.event_time) < cut]
    after = [r.attributes["value"] for r in rows if _aware(r.event_time) >= cut]
    if len(before) < 3 or len(after) < 3:
        return DiagnosticResult("inconclusive", 0.0, "Too few database metric points before or after onset to compare.",
                                {"before": len(before), "after": len(after)})
    b, a = statistics.median(before), statistics.median(after)
    details = {"median_before": b, "median_after": a}
    refs = [r.event_id for r in rows[-5:]]
    if a >= 3 * max(b, 1.0):
        return DiagnosticResult("supports", 0.9, f"Median database time rose from {b:.0f} ms to {a:.0f} ms.", details, refs)
    return DiagnosticResult("contradicts", 0.7, f"Database time did not rise materially (median {b:.0f} ms before, {a:.0f} ms after).", details, refs)


def inspect_db_pool_acquire_wait(ctx: Context) -> DiagnosticResult:
    """If the pool is exhausted, slow requests should spend their time waiting for a connection."""
    shares, traced = _share_in_spans(ctx, lambda k: _span_name(k).startswith("db.pool"))
    if len(traced) < 3:
        return DiagnosticResult("no_data", 0.0, "Fewer than 3 slow requests were traced, so connection waits cannot be measured.",
                                {"looked_for": ["db.pool.* spans in request traces"]})
    med = statistics.median(shares)
    details = {"traced_slow_requests": len(traced), "median_share_waiting_for_connection": round(med, 3)}
    refs = [k.event_id for _, kids in traced[:3] for k in kids if _span_name(k).startswith("db.pool")][:5]
    if med >= 0.5:
        return DiagnosticResult("supports", 0.9, f"Slow requests spent {med:.0%} of their time waiting for a database connection (median over {len(traced)} traces).", details, refs)
    if med <= 0.1:
        return DiagnosticResult("contradicts", 0.8, f"Slow requests spent only {med:.0%} of their time waiting for a connection; the pool is not the bottleneck.", details,
                                [k.event_id for _, kids in traced[:3] for k in kids[:1]])
    return DiagnosticResult("inconclusive", 0.0, f"Connection waits are {med:.0%} of the slow requests' time: a factor, not clearly the cause.", details, refs)


def inspect_cache_spans(ctx: Context) -> DiagnosticResult:
    """If the cache is down, slow requests should carry a failed or hung cache call."""
    traced = [(s, kids) for s, kids in ((s, _child_spans(ctx, s)) for s in ctx.features.bad) if kids]
    if len(traced) < 3:
        return DiagnosticResult("no_data", 0.0, "Fewer than 3 slow requests were traced, so cache calls cannot be checked.",
                                {"looked_for": ["cache.* spans in request traces"]})

    def broken(kids):
        return [k for k in kids if _span_name(k).startswith("cache.")
                and ((k.attributes or {}).get("status") == "error" or _span_ms(k) >= 200)]
    hits = [(s, broken(kids)) for s, kids in traced]
    share = sum(1 for _, b in hits if b) / len(traced)
    details = {"traced_slow_requests": len(traced), "with_failed_cache_call": sum(1 for _, b in hits if b)}
    refs = [b[0].event_id for _, b in hits if b][:5]
    if share >= 0.8:
        return DiagnosticResult("supports", 0.9, f"{share:.0%} of slow requests had a failed or hung cache call.", details, refs)
    if share <= 0.2:
        return DiagnosticResult("contradicts", 0.8, f"Only {share:.0%} of slow requests had a cache problem; the cache is not the cause.", details,
                                [s.event_id for s, _ in traced[:5]])
    return DiagnosticResult("inconclusive", 0.0, f"{share:.0%} of slow requests had a cache problem.", details, refs)


def inspect_cpu_time(ctx: Context) -> DiagnosticResult:
    """If the service is CPU-bound, slow requests should spend their time on-CPU (cpu_ms on the root span)."""
    pairs = []
    for s in ctx.features.bad:
        root = _root_span(ctx, s)
        cpu = (root.attributes or {}).get("cpu_ms") if root else None
        if isinstance(cpu, (int, float)) and not isinstance(cpu, bool):
            pairs.append((s, root, min(1.0, float(cpu) / max(s.duration_ms, 1.0))))
    if len(pairs) < 3:
        return DiagnosticResult("no_data", 0.0, "Fewer than 3 slow requests report cpu_ms on their spans, so CPU time cannot be measured.",
                                {"looked_for": ["cpu_ms attribute on request root spans"]})
    med = statistics.median(p[2] for p in pairs)
    details = {"slow_requests_with_cpu_time": len(pairs), "median_share_on_cpu": round(med, 3)}
    refs = [r.event_id for _, r, _ in pairs[:5]]
    if med >= 0.5:
        return DiagnosticResult("supports", 0.9, f"Slow requests spent {med:.0%} of their time on-CPU (median over {len(pairs)}).", details, refs)
    if med <= 0.2:
        return DiagnosticResult("contradicts", 0.8, f"Slow requests spent only {med:.0%} of their time on-CPU; they were waiting, not computing.", details, refs)
    return DiagnosticResult("inconclusive", 0.0, f"Slow requests spent {med:.0%} of their time on-CPU.", details, refs)


def inspect_retry_amplification(ctx: Context) -> DiagnosticResult:
    """A retry storm multiplies provider calls per request; one call per request rules it out."""
    def calls(s: Sample) -> int:
        return sum(1 for k in _child_spans(ctx, s) if _span_name(k).startswith("payment."))
    traced = [(s, calls(s)) for s in ctx.features.bad if s.route == "/api/checkout" and _child_spans(ctx, s)]
    retried = {rid for _, _, rid in ctx.features.retry_events if rid}
    if len(traced) < 3:
        if not ctx.features.bad or not retried:
            return DiagnosticResult("no_data", 0.0, "Too few traced checkouts and no retry logs: provider calls per request cannot be counted.",
                                    {"looked_for": ["payment.* spans per checkout trace", "payment_retry log lines"]})
        share = sum(1 for s in ctx.features.bad if s.request_id in retried) / len(ctx.features.bad)
        details = {"failing_requests": len(ctx.features.bad), "share_with_retry_logs": round(share, 3), "source": "logs"}
        if share >= 0.6:
            return DiagnosticResult("supports", 0.8, f"{share:.0%} of failing requests logged provider retries.", details,
                                    [e for e, _, _ in ctx.features.retry_events[:5]])
        return DiagnosticResult("inconclusive", 0.0, f"Only {share:.0%} of failing requests logged provider retries.", details)
    med = statistics.median(n for _, n in traced)
    details = {"traced_checkouts": len(traced), "median_provider_calls_per_request": med, "source": "traces"}
    refs = [s.event_id for s, n in traced if n > 1][:5] or [s.event_id for s, _ in traced[:5]]
    if med >= 3:
        return DiagnosticResult("supports", 0.9, f"Each failing checkout called the provider {med:g} times (median over {len(traced)} traces): retries amplify every failure.", details, refs)
    if med <= 1:
        return DiagnosticResult("contradicts", 0.8, f"Failing checkouts called the provider {med:g} time (median over {len(traced)} traces): there is no retry amplification.", details, refs)
    return DiagnosticResult("inconclusive", 0.0, f"Failing checkouts called the provider {med:g} times (median): some retrying, not clearly a storm.", details, refs)


def compare_request_rate_to_baseline(ctx: Context) -> DiagnosticResult:
    ratio = ctx.features.volume_ratio
    if ratio is None:
        return DiagnosticResult("no_data", 0.0, "Not enough baseline traffic to compare request rate.")
    details = {"rate_ratio": round(ratio, 2)}
    if ratio >= 3:
        return DiagnosticResult("supports", 0.9, f"Request rate is {ratio:.1f}x baseline.", details)
    if ratio <= 1.5:
        return DiagnosticResult("contradicts", 0.9, f"Request rate is {ratio:.1f}x baseline: no traffic surge.", details)
    return DiagnosticResult("inconclusive", 0.0, f"Request rate is {ratio:.1f}x baseline: elevated but not a clear surge.", details)


# The allow-list. Keys are the only test ids the API will accept; values are read-only functions.
TESTS = {
    "compare_error_rate_before_after_release": ("release_regression", compare_error_rate_before_after_release),
    "inspect_payment_provider_status_and_spans": ("payment_provider_timeout", inspect_payment_provider_status_and_spans),
    "inspect_db_pool_wait_and_query_duration": ("slow_dependency", inspect_db_pool_wait_and_query_duration),
    "compare_request_rate_to_baseline": ("traffic_surge", compare_request_rate_to_baseline),
    "inspect_db_pool_acquire_wait": ("db_pool_exhaustion", inspect_db_pool_acquire_wait),
    "inspect_cache_spans": ("cache_unavailable", inspect_cache_spans),
    "inspect_cpu_time": ("resource_saturation", inspect_cpu_time),
    "inspect_retry_amplification": ("retry_storm", inspect_retry_amplification),
}


def retry_events(rows) -> list[tuple[str, datetime, str | None]]:
    return [(r.event_id, _aware(r.event_time), r.request_id) for r in rows if (r.attributes or {}).get("message") == "payment_retry"]


def load_context(session: Session, incident: IncidentRow, cfg: DetectionConfig = DetectionConfig()) -> Context | None:
    """Rebuild the incident's analysis context from stored events as of its detection time."""
    as_of = _aware(incident.detected_at)
    rows = list(session.scalars(select(EventRow).where(
        EventRow.tenant_id == incident.tenant_id,
        EventRow.event_time >= as_of - timedelta(seconds=LOOKBACK_SECONDS), EventRow.event_time <= as_of)))
    samples = samples_from_rows(rows)
    mine = set(incident.routes)
    cand = next((c for c in group(detect(samples, as_of, cfg), as_of, cfg) if mine & set(c.routes)), None)
    if cand is None:
        return None
    timeouts = [(r.event_id, _aware(r.event_time), r.request_id) for r in rows
                if (r.attributes or {}).get("message") == "payment_timeout"]
    feats = compute_features(cand, samples, [(i, t) for i, t, _ in timeouts], retry_events(rows))
    spans: dict[str, list[EventRow]] = {}
    for r in rows:
        if r.event_type == "trace" and r.trace_id:
            spans.setdefault(r.trace_id, []).append(r)
    return Context(cand, feats, samples, timeouts, [r for r in rows if r.event_type == "metric"], spans)


# ---- persistence + rescoring ---------------------------------------------------------------

def _hypotheses(session: Session, incident_id: str) -> list[HypothesisRow]:
    return list(session.scalars(select(HypothesisRow).where(HypothesisRow.incident_id == incident_id)))


def rescore(session: Session, incident: IncidentRow, reason: str) -> None:
    """Recompute scores from ALL ledger evidence; keep the previous score in score_history."""
    rows = _hypotheses(session, incident.id)
    ev = list(session.scalars(select(EvidenceRow).where(EvidenceRow.incident_id == incident.id)))
    hyps = []
    for r in rows:
        items = [EvidenceItem(e.relation, e.strength, e.explanation, e.source_refs, e.query_fingerprint, e.created_by)
                 for e in ev if e.hypothesis_id == r.id]
        hyps.append(Hypothesis(r.cause_key, r.title, items, r.breakdown.get("raw_temporal", 0.0),
                               r.breakdown.get("raw_dependency", 0.0), r.next_test_id))
    ranked, assessment = rank(hyps)
    by_key = {h.cause_key: h for h in ranked}
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        h = by_key[r.cause_key]
        if (r.score, r.status) != (h.score, h.status):
            r.score_history = [*(r.score_history or []), {"at": now, "score": r.score, "status": r.status, "reason": reason}]
        r.score, r.status, r.breakdown = h.score, h.status, h.breakdown
    incident.assessment = assessment


def run_test(session: Session, incident: IncidentRow, test_id: str, cfg: DetectionConfig = DetectionConfig()) -> DiagnosticRunRow:
    if test_id not in TESTS:
        raise KeyError(test_id)
    cause_key, fn = TESTS[test_id]
    ctx = load_context(session, incident, cfg)
    t0 = time.perf_counter()
    result = fn(ctx) if ctx else DiagnosticResult("no_data", 0.0, "The incident's anomaly is no longer reproducible from stored events.")
    duration_ms = int((time.perf_counter() - t0) * 1000)

    # Replace any earlier run of the same test (and its evidence); the score history keeps the past.
    session.execute(delete(EvidenceRow).where(EvidenceRow.incident_id == incident.id,
                                              EvidenceRow.created_by == f"diagnostic:{test_id}"))
    session.execute(delete(DiagnosticRunRow).where(DiagnosticRunRow.incident_id == incident.id,
                                                   DiagnosticRunRow.test_id == test_id))
    session.flush()
    run = DiagnosticRunRow(id=str(uuid.uuid4()), incident_id=incident.id, test_id=test_id, hypothesis_key=cause_key,
                           outcome=result.outcome, explanation=result.explanation,
                           details={**result.details, "strength": result.strength},
                           source_refs=result.source_refs, duration_ms=duration_ms, created_at=datetime.now(timezone.utc))
    session.add(run)
    hyp = next((h for h in _hypotheses(session, incident.id) if h.cause_key == cause_key), None)
    if hyp and result.outcome in ("supports", "contradicts"):
        valid = {e for e in session.scalars(select(EventRow.event_id).where(
            EventRow.tenant_id == incident.tenant_id, EventRow.event_id.in_(result.source_refs or [""])))}
        fp = hashlib.sha256(f"{test_id}|{incident.id}".encode()).hexdigest()[:16]
        session.add(EvidenceRow(id=str(uuid.uuid4()), incident_id=incident.id, hypothesis_id=hyp.id,
                                relation=result.outcome, strength=result.strength, explanation=result.explanation,
                                source_refs=[r for r in result.source_refs if r in valid],
                                query_fingerprint=fp, created_by=f"diagnostic:{test_id}"))
    session.flush()
    rescore(session, incident, reason=f"diagnostic:{test_id}:{result.outcome}")
    return run


def reapply(session: Session, incident: IncidentRow, test_ids: list[str], cfg: DetectionConfig = DetectionConfig()) -> None:
    for t in test_ids:
        run_test(session, incident, t, cfg)


# ---- the investigation loop ----------------------------------------------------------------

STRONG_SUPPORT = 0.8  # a leader "survives" only a test that could have refuted it and clearly did not


def _leader_test(session: Session, incident_id: str, test_id: str) -> DiagnosticRunRow | None:
    return session.scalar(select(DiagnosticRunRow).where(
        DiagnosticRunRow.incident_id == incident_id, DiagnosticRunRow.test_id == test_id))


def _strongly_supported(run: DiagnosticRunRow | None) -> bool:
    return bool(run) and run.outcome == "supports" and float((run.details or {}).get("strength", 0)) >= STRONG_SUPPORT


def investigate(session: Session, incident: IncidentRow, budget: int = 4, cfg: DetectionConfig = DetectionConfig()) -> dict:
    """Try to falsify the leading hypothesis. Stops when the leader survives a real test, is
    overturned, cannot be tested for lack of data, or the budget is spent."""
    steps: list[dict] = []
    start_leader = None
    stop = "budget_exhausted"

    def ranked_rows():
        return sorted(_hypotheses(session, incident.id), key=lambda h: (h.status != "falsified", h.score), reverse=True)

    for _ in range(max(0, budget)):
        ranked = ranked_rows()
        leader = ranked[0]
        start_leader = start_leader or leader.cause_key
        done = set(session.scalars(select(DiagnosticRunRow.test_id).where(DiagnosticRunRow.incident_id == incident.id)))
        # Test the leader first; once it is tested, test live alternatives to separate them.
        order = [leader] + [h for h in ranked[1:] if h.status in ("alternative", "uncertain")]
        order = [h for h in order if h.status != "falsified"]
        pick = next((h.next_test_id for h in order if h.next_test_id not in done and h.next_test_id in TESTS), None)
        if pick is None:
            leader_run = _leader_test(session, incident.id, leader.next_test_id)
            if leader_run and leader_run.outcome == "no_data":
                stop = "leader_untestable_missing_data"
            elif incident.assessment == "leading_hypothesis":
                # Either the leader passed a decisive test, or its own test was only suggestive but
                # every live alternative has now been tested and none overtook it.
                stop = "leader_survived_falsification" if _strongly_supported(leader_run) else "leader_stands_alternatives_ruled_out"
            else:
                stop = "no_runnable_tests"
            break
        run = run_test(session, incident, pick, cfg)
        now_leader = ranked_rows()[0]
        steps.append({"test_id": pick, "tested_hypothesis": run.hypothesis_key, "outcome": run.outcome,
                      "explanation": run.explanation, "leader_after": now_leader.cause_key,
                      "assessment_after": incident.assessment})
        # Stop early only on a decisive confirmation; weak support keeps testing the alternatives.
        if (pick == leader.next_test_id and _strongly_supported(run) and incident.assessment == "leading_hypothesis"
                and now_leader.cause_key == leader.cause_key):
            stop = "leader_survived_falsification"
            break
    final = ranked_rows()[0]
    return {"steps": steps, "stop_reason": stop, "started_with": start_leader, "leader": final.cause_key,
            "leader_changed": final.cause_key != start_leader, "assessment": incident.assessment}
