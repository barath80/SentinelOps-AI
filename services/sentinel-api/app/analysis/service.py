"""Runs detection over stored events and persists incidents, hypotheses and evidence."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import DiagnosticRunRow, EvidenceRow, EventRow, HypothesisRow, IncidentRow
from . import learned, propagation, quality
from .attribution import attribute
from .ml_features import features_for_candidate
from .diagnostics import reapply, retry_events
from .detect import DetectionConfig, IncidentCandidate, detect, group, samples_from_rows
from .hypotheses import SCORE_VERSION, build_hypotheses, compute_features, rank

CREATED_BY = f"rule:{SCORE_VERSION}"
QUALITY_LOOKAHEAD_S = 300  # ingest rejects events further ahead than this anyway


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _severity(c: IncidentCandidate) -> str:
    worst = max((a.recent_error_rate for a in c.anomalies), default=0.0)
    if worst >= 0.5:
        return "critical"
    return "error" if worst >= 0.1 else "warning"


def _title(c: IncidentCandidate) -> str:
    parts = [f"{a.route}: {'elevated 5xx errors' if a.kind == 'errors' else 'latency regression'}" for a in c.anomalies]
    return "; ".join(parts)[:200]


def analyze(session: Session, tenant_id: str, as_of: datetime, window_seconds: int = 900,
            cfg: DetectionConfig = DetectionConfig(), shadow: bool = True) -> list[str]:
    """Detect incidents in [as_of - window, as_of]. Returns incident ids (created or refreshed)."""
    as_of = _aware(as_of)
    since = as_of - timedelta(seconds=window_seconds)
    rows = list(session.scalars(
        select(EventRow).where(EventRow.tenant_id == tenant_id, EventRow.event_time >= since, EventRow.event_time <= as_of)
    ))
    samples = samples_from_rows(rows)
    timeouts = [(r.event_id, _aware(r.event_time)) for r in rows if (r.attributes or {}).get("message") == "payment_timeout"]
    timeouts_with_ids = [(r.event_id, _aware(r.event_time), r.request_id) for r in rows
                         if (r.attributes or {}).get("message") == "payment_timeout"]
    retries = retry_events(rows)
    # Events stamped after as_of are outside detection, but they are exactly how a fast clock shows up.
    ahead = list(session.scalars(select(EventRow).where(
        EventRow.tenant_id == tenant_id, EventRow.event_time > as_of, EventRow.event_time <= as_of + timedelta(seconds=QUALITY_LOOKAHEAD_S))))
    data_quality = quality.assess(rows + ahead)
    spans: dict[str, list] = {}
    for r in rows:
        if r.event_type == "trace" and r.trace_id:
            spans.setdefault(r.trace_id, []).append(r)
    valid_event_ids = {r.event_id for r in rows}

    ids: list[str] = []
    for cand in group(detect(samples, as_of, cfg), as_of, cfg):
        timeouts_for_features = timeouts
        feats = compute_features(cand, samples, timeouts, retries)
        ranked, assessment = rank(build_hypotheses(cand, feats))
        rule_answer = ranked[0].cause_key if assessment == "leading_hypothesis" else "unknown"
        model_features = features_for_candidate(cand, samples, feats, timeouts_with_ids)
        shadow_result = None
        model = learned.load() if shadow else None
        if model is not None:
            # Shadow mode: recorded next to the rule engine's answer, never used for any decision.
            pred = model.predict(model_features)
            shadow_result = {**pred, "rule_answer": rule_answer, "agrees_with_rules": pred["prediction"] == rule_answer,
                             "mode": "shadow: recorded only, never used for decisions"}
        incident = _find_open(session, tenant_id, cand, cfg)
        prior_tests: list[str] = []
        history: dict[str, list] = {}
        if incident is not None:  # keep what an earlier investigation learned across re-analysis
            prior_tests = list(session.scalars(select(DiagnosticRunRow.test_id).where(DiagnosticRunRow.incident_id == incident.id)))
            history = {h.cause_key: list(h.score_history or []) for h in session.scalars(
                select(HypothesisRow).where(HypothesisRow.incident_id == incident.id))}
        if incident is None:
            incident = IncidentRow(id=str(uuid.uuid4()), tenant_id=tenant_id, status="open")
            session.add(incident)
        else:  # refresh: conclusions can change as more data arrives
            session.execute(delete(EvidenceRow).where(EvidenceRow.incident_id == incident.id))
            session.execute(delete(HypothesisRow).where(HypothesisRow.incident_id == incident.id))
        incident.title = _title(cand)
        incident.severity = _severity(cand)
        incident.assessment = assessment
        incident.started_at = cand.onset
        incident.detected_at = as_of
        incident.routes = cand.routes
        incident.summary = {
            "anomalies": [{
                "route": a.route, "kind": a.kind, "recent_requests": a.recent_n, "baseline_requests": a.baseline_n,
                "recent_error_rate": round(a.recent_error_rate, 4), "baseline_error_rate": round(a.baseline_error_rate, 4),
                "recent_p95_ms": a.recent_p95_ms, "baseline_p95_ms": a.baseline_p95_ms,
            } for a in cand.anomalies],
            "unaffected_routes": feats.unaffected_routes,
            **attribute(cand, samples, timeouts_for_features, retries),
            "model_features": {k: round(v, 6) for k, v in model_features.items()},
            "rule_answer": rule_answer,
            "shadow_model": shadow_result,
            "telemetry_quality": data_quality,
            "propagation": propagation.build(cand, samples, spans),
        }
        session.flush()
        for h in ranked:
            hid = str(uuid.uuid4())
            session.add(HypothesisRow(id=hid, incident_id=incident.id, cause_key=h.cause_key, title=h.title,
                                      score=h.score, score_version=SCORE_VERSION, status=h.status,
                                      next_test_id=h.next_test_id, breakdown=h.breakdown,
                                      score_history=history.get(h.cause_key, [])))
            session.flush()
            for e in h.evidence:
                # Ledger rule: every cited source must be a stored event of this tenant.
                refs = [r for r in e.source_refs if r in valid_event_ids]
                session.add(EvidenceRow(id=str(uuid.uuid4()), incident_id=incident.id, hypothesis_id=hid,
                                        relation=e.relation, strength=e.strength, explanation=e.explanation,
                                        source_refs=refs, query_fingerprint=e.query_fingerprint, created_by=CREATED_BY))
        session.flush()
        if prior_tests:
            reapply(session, incident, prior_tests, cfg)
        ids.append(incident.id)
    return ids


def _find_open(session: Session, tenant_id: str, cand: IncidentCandidate, cfg: DetectionConfig) -> IncidentRow | None:
    slack = timedelta(seconds=cfg.group_seconds * 2)
    for inc in session.scalars(select(IncidentRow).where(IncidentRow.tenant_id == tenant_id, IncidentRow.status == "open")):
        if abs(_aware(inc.started_at) - cand.onset) <= slack and set(inc.routes) & set(cand.routes):
            return inc
    return None
