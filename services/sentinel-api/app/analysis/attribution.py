"""Per-symptom attribution: does ONE cause explain every symptom of an incident?

The incident-level ranking treats all anomalies together, which can force a single winner onto
an incident with two unrelated faults. Here each anomaly (route + kind) is ranked on its own with
the same rules. The result is reported next to, not instead of, the incident-level ranking:

  single_cause   every symptom has the same leading cause
  multi_cause    every symptom has a leading cause and they differ
  partial        some symptoms have a leading cause, others are unexplained
  unexplained    no symptom has a clear cause
"""
from __future__ import annotations

from datetime import datetime

from .detect import IncidentCandidate, Sample
from .hypotheses import build_hypotheses, compute_features, rank


def attribute(cand: IncidentCandidate, samples: list[Sample], timeouts: list[tuple[str, datetime]],
              retries: list[tuple[str, datetime, str | None]] = ()) -> dict:
    symptoms = []
    for a in cand.anomalies:
        sub = IncidentCandidate([a], a.onset, cand.recent_start, cand.as_of)
        ranked, assessment = rank(build_hypotheses(sub, compute_features(sub, samples, timeouts, retries)))
        top = ranked[0]
        symptoms.append({
            "route": a.route, "kind": a.kind,
            "cause": top.cause_key if assessment == "leading_hypothesis" else None,
            "top_candidate": top.cause_key, "top_score": top.score,
            "runner_up": ranked[1].cause_key if len(ranked) > 1 else None,
            "runner_up_score": ranked[1].score if len(ranked) > 1 else None,
        })
    causes = sorted({s["cause"] for s in symptoms if s["cause"]})
    unexplained = [s for s in symptoms if s["cause"] is None]
    if not unexplained and len(causes) == 1:
        kind = "single_cause"
    elif not unexplained:
        kind = "multi_cause"
    elif causes:
        kind = "partial"
    else:
        kind = "unexplained"
    return {"attribution": kind, "causes": causes, "symptoms": symptoms,
            "unexplained_symptoms": [f"{s['route']} ({s['kind']})" for s in unexplained]}
