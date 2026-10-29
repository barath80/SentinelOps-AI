"""Incident insights: timeline, similar past incidents, postmortem draft, SLOs and error budgets.

All read-only, all computed from stored records, and every statement in a postmortem points back to
the evidence or event it came from. The postmortem is a draft for people to edit: SentinelOps never
publishes it anywhere.
"""
import math
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from .analysis import learned
from .analysis.detect import percentile, samples_from_rows
from .analysis.diagnostics import investigated_answer
from .db import (AutomationRunRow, ContractRow, DiagnosticRunRow, EventRow, EvidenceRow, HypothesisRow, IncidentLabelRow,
                 IncidentRow, NotificationRow, PreventionArtifactRow, TransitionRow, VerificationRow)

AVAILABILITY_TARGET = 0.99  # the contracts' error-rate condition (<= 1%) as an SLO
LATENCY_TARGET_MS = 500  # the contracts' latency floor
FAST_BURN = 14.4  # Google SRE workbook: 2% of a 30-day budget in 1 hour


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---- timeline -----------------------------------------------------------------------------

def timeline(session, inc: IncidentRow) -> list[dict]:
    end = _aware(inc.detected_at)
    start = end - timedelta(seconds=(inc.summary or {}).get("analysis_window_seconds") or 900)
    rows = list(session.scalars(select(EventRow).where(EventRow.tenant_id == inc.tenant_id, EventRow.event_time >= start,
                                                       EventRow.event_time <= end + timedelta(minutes=30))))
    items: list[dict] = []
    add = lambda at, kind, text, ref=None, actor=None: items.append(
        {"at": _aware(at).isoformat(), "kind": kind, "text": text, "ref": ref, "actor": actor})
    for a in (inc.summary or {}).get("anomalies", []):
        add(inc.started_at, "symptom", f"{a['route']}: {'errors' if a['kind'] == 'errors' else 'latency'} began "
            f"(error rate {a['recent_error_rate']:.0%}, p95 {round(a['recent_p95_ms'])} ms)")
    samples = [s for s in samples_from_rows(rows) if s.time <= end]
    before = {s.version for s in samples if s.time < _aware(inc.started_at) - timedelta(minutes=2) and s.version}
    seen = set()
    for s in samples:
        if s.version and s.version not in before and s.version not in seen:
            seen.add(s.version)
            add(s.time, "release", f"release {s.version} first seen on {s.route}", s.event_id)
    near = _aware(inc.started_at) - timedelta(seconds=120)
    for message, text in (("payment_timeout", "first payment timeout logged"), ("payment_retry", "first payment retry logged")):
        first = min((r for r in rows if (r.attributes or {}).get("message") == message and _aware(r.event_time) >= near),
                    key=lambda r: _aware(r.event_time), default=None)
        # only signals near the onset belong to this incident (an earlier, unrelated fault can sit in the window)
        if first is not None and _aware(first.event_time) >= _aware(inc.started_at) - timedelta(seconds=120):
            add(first.event_time, "signal", text, first.event_id)
    add(inc.detected_at, "detected", f"incident raised: {inc.title}")
    for d in session.scalars(select(DiagnosticRunRow).where(DiagnosticRunRow.incident_id == inc.id)):
        add(d.created_at, "diagnostic", f"{d.test_id}: {d.outcome}. {d.explanation}")
    for t, c in session.execute(select(TransitionRow, ContractRow).join(ContractRow, ContractRow.id == TransitionRow.contract_id)
                                .where(ContractRow.incident_id == inc.id)):
        add(t.at, "recovery", f"{c.action_template}: {t.from_state or 'start'} to {t.to_state}" + (f" ({t.note})" if t.note else ""),
            None, t.actor)
    for n in session.scalars(select(NotificationRow).where(NotificationRow.status == "sent")):
        if (n.payload or {}).get("incident_id") == inc.id:
            add(n.sent_at or n.created_at, "notified", f"team notified: {n.event}")
    for r in session.scalars(select(AutomationRunRow).where(AutomationRunRow.incident_id == inc.id)):
        add(r.at, "automation", f"automation {r.step}: {r.outcome}" + (f" ({r.reason})" if r.reason else ""), None, "automation")
    lab = session.get(IncidentLabelRow, inc.id)
    if lab:
        add(lab.labeled_at, "label", f"labelled {lab.label}", None, lab.labeled_by)
    order = {"symptom": 1, "release": 0, "signal": 2, "detected": 3}
    return sorted(items, key=lambda x: (x["at"], order.get(x["kind"], 5)))


# ---- similar incidents ---------------------------------------------------------------------

def _vector(model, feats: dict) -> list[float] | None:
    if not feats or any(f not in feats for f in model.features):
        return None
    return [(float(feats[f]) - m) / s for f, m, s in zip(model.features, model.mean, model.scale)]


def similar(session, inc: IncidentRow, top: int = 5) -> list[dict]:
    """Earlier incidents whose feature vectors point the same way, with what they turned out to be."""
    model = learned.load()
    if model is None:
        return []
    me = _vector(model, (inc.summary or {}).get("model_features") or {})
    if me is None:
        return []
    out = []
    for other in session.scalars(select(IncidentRow).where(IncidentRow.tenant_id == inc.tenant_id, IncidentRow.id != inc.id,
                                                           IncidentRow.started_at < inc.started_at)):
        v = _vector(model, (other.summary or {}).get("model_features") or {})
        if v is None:
            continue
        dot = sum(a * b for a, b in zip(me, v))
        norm = math.sqrt(sum(a * a for a in me)) * math.sqrt(sum(b * b for b in v))
        if not norm:
            continue
        lab = session.get(IncidentLabelRow, other.id)
        fixed = session.scalars(select(ContractRow).where(ContractRow.incident_id == other.id, ContractRow.state == "SUCCEEDED")).first()
        out.append({"incident_id": other.id, "title": other.title, "started_at": _aware(other.started_at).isoformat(),
                    "similarity": round(dot / norm, 3), "status": other.status,
                    "cause": lab.label if lab else investigated_answer(session, other) or (other.summary or {}).get("rule_answer"),
                    "cause_source": "label" if lab else "investigation",
                    "resolved_by": fixed.action_template if fixed else None})
    return sorted(out, key=lambda x: -x["similarity"])[:top]


# ---- postmortem ------------------------------------------------------------------------------

def postmortem(session, inc: IncidentRow) -> str:
    sm = inc.summary or {}
    hyps = sorted(session.scalars(select(HypothesisRow).where(HypothesisRow.incident_id == inc.id)),
                  key=lambda h: (h.status != "falsified", h.score), reverse=True)
    lead = hyps[0] if hyps and inc.assessment == "leading_hypothesis" else None
    ev = list(session.scalars(select(EvidenceRow).where(EvidenceRow.incident_id == inc.id)))
    contracts = list(session.scalars(select(ContractRow).where(ContractRow.incident_id == inc.id).order_by(ContractRow.created_at)))
    resolved_at = None
    for c in contracts:
        v = session.scalars(select(VerificationRow).where(VerificationRow.contract_id == c.id, VerificationRow.outcome == "pass")).first()
        if v:
            resolved_at = _aware(v.window_end)
    start = _aware(inc.started_at)
    L = [f"# Postmortem (draft): {inc.title}", "",
         f"*Generated by SentinelOps from stored evidence on {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. A draft for people to review and edit.*", "",
         "## Summary", "",
         f"- **Status:** {inc.status}. **Severity:** {inc.severity}. **Assessment:** {inc.assessment.replace('_', ' ')}.",
         f"- **Started:** {start:%Y-%m-%d %H:%M:%S} UTC. **Detected:** {_aware(inc.detected_at):%H:%M:%S} UTC"
         + (f". **Resolved (verified):** {resolved_at:%H:%M:%S} UTC, {round((resolved_at - start).total_seconds() / 60, 1)} min after onset." if resolved_at else "."),
         f"- **Cause:** {lead.title} (`{lead.cause_key}`, score {lead.score}, a ranking, not a probability)." if lead
         else "- **Cause:** not determined. The evidence did not single out one cause.", "",
         "## Impact", ""]
    for a in sm.get("anomalies", []):
        L.append(f"- `{a['route']}`: {a['kind']}. Error rate {a['recent_error_rate']:.0%} (baseline {a['baseline_error_rate']:.0%}); "
                 f"p95 {round(a['recent_p95_ms'])} ms" + (f" (baseline {round(a['baseline_p95_ms'])} ms)" if a.get("baseline_p95_ms") else "")
                 + f"; {a['recent_requests']} requests in the detection window.")
    if sm.get("unaffected_routes"):
        L.append(f"- Unaffected: {', '.join(f'`{r}`' for r in sm['unaffected_routes'])}.")
    L += ["", "## Root cause and evidence", ""]
    for h in hyps:
        mine = [e for e in ev if e.hypothesis_id == h.id and e.relation in ("supports", "contradicts")]
        L.append(f"### {h.title} ({h.status}, score {h.score})")
        for e in sorted(mine, key=lambda e: -e.strength):
            refs = ", ".join(f"`{r[:8]}`" for r in e.source_refs[:3])
            L.append(f"- {e.relation} ({e.strength}): {e.explanation}" + (f" Sources: {refs}." if refs else ""))
        if not mine:
            L.append("- No direct evidence either way.")
        L.append("")
    prop = (sm.get("propagation") or {}).get("earliest_containment")
    if prop:
        L += ["## Where it could have been contained", "", f"- **{prop['node']}**: {prop['how']}. {prop['reason']}.", ""]
    L += ["## Timeline (UTC)", ""]
    for t in timeline(session, inc):
        L.append(f"- {datetime.fromisoformat(t['at']):%H:%M:%S} {t['kind']}: {t['text']}" + (f" ({t['actor']})" if t.get("actor") else ""))
    L += ["", "## What was done", ""]
    if not contracts:
        L.append("- No recovery action was taken through SentinelOps.")
    for c in contracts:
        body = c.contract or {}
        verdicts = [v for v in session.scalars(select(VerificationRow).where(VerificationRow.contract_id == c.id))]
        L.append(f"- `{c.action_template}` proposed by {c.proposed_by}: final state **{c.state}**, outcome **{c.outcome}**. "
                 f"Rehearsal: {(body.get('rehearsal') or {}).get('outcome', 'n/a')}."
                 + "".join(f" Verification: {v.outcome} ({v.reason})." for v in verdicts))
    arts = list(session.scalars(select(PreventionArtifactRow).where(PreventionArtifactRow.incident_id == inc.id)))
    L += ["", "## Prevention", ""]
    L += [f"- {a.title} ({a.artifact_type}, review: {a.review_status})." for a in arts] or ["- No prevention proposals yet (generated once a recovery is verified)."]
    missing = sorted({e.explanation for e in ev if e.relation == "missing"})
    L += ["", "## Open questions (missing evidence)", ""] + [f"- {m}" for m in missing] + [
        "", "## Learned model (shadow)", "",
        f"- Predicted `{(sm.get('shadow_model') or {}).get('prediction', 'n/a')}`; recorded only, it did not influence any decision.", ""]
    return "\n".join(L)


# ---- SLOs and error budgets -------------------------------------------------------------------

def slos(rows, now: datetime) -> list[dict]:
    """Per route: availability (5xx) and latency (p95) against the contract targets, budget and burn."""
    samples = [s for s in samples_from_rows(rows) if not s.route.startswith("/api/admin") and s.time <= now]
    out = []
    for route in sorted({s.route for s in samples}):
        mine = [s for s in samples if s.route == route]
        day = [s for s in mine if s.time >= now - timedelta(hours=24)]
        hour = [s for s in mine if s.time >= now - timedelta(hours=1)]
        if not day:
            continue
        err = lambda xs: sum(s.is_error for s in xs) / len(xs) if xs else 0.0
        budget = 1 - AVAILABILITY_TARGET
        slow = lambda xs: sum(s.duration_ms > LATENCY_TARGET_MS for s in xs) / len(xs) if xs else 0.0
        burn_1h = err(hour) / budget if hour else 0.0
        out.append({
            "route": route, "requests_24h": len(day), "requests_1h": len(hour),
            "availability_24h": round(1 - err(day), 5), "availability_target": AVAILABILITY_TARGET,
            "error_budget_remaining": round(max(0.0, 1 - err(day) / budget), 4),
            "burn_rate_1h": round(burn_1h, 2), "fast_burn": burn_1h >= FAST_BURN and len(hour) >= 20,
            "p95_ms_24h": percentile([s.duration_ms for s in day], 95), "latency_target_ms": LATENCY_TARGET_MS,
            "within_latency_target_24h": round(1 - slow(day), 4),
        })
    return out


def register(app: FastAPI, tenant_id: str, sessions, auth) -> None:
    read = auth.require("read")

    def incident(s, incident_id):
        inc = s.get(IncidentRow, incident_id)
        if inc is None or inc.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="not_found")
        return inc

    @app.get("/api/v1/incidents/{incident_id}/timeline")
    def get_timeline(incident_id: str, _p: Annotated[object, Depends(read)]) -> list[dict]:
        with sessions() as s:
            return timeline(s, incident(s, incident_id))

    @app.get("/api/v1/incidents/{incident_id}/similar")
    def get_similar(incident_id: str, _p: Annotated[object, Depends(read)]) -> list[dict]:
        with sessions() as s:
            return similar(s, incident(s, incident_id))

    @app.get("/api/v1/incidents/{incident_id}/postmortem", response_class=PlainTextResponse)
    def get_postmortem(incident_id: str, _p: Annotated[object, Depends(read)]) -> str:
        with sessions() as s:
            return postmortem(s, incident(s, incident_id))

    @app.get("/api/v1/slo")
    def get_slos(_p: Annotated[object, Depends(read)], hours: Annotated[int, Query(ge=1, le=168)] = 24) -> dict:
        now = datetime.now(timezone.utc)
        with sessions() as s:
            rows = list(s.scalars(select(EventRow).where(EventRow.tenant_id == tenant_id, EventRow.event_type == "log",
                                                         EventRow.event_time >= now - timedelta(hours=max(24, hours)))))
        return {"as_of": now.isoformat(), "fast_burn_threshold": FAST_BURN,
                "method": "availability = share of requests without a 5xx; budget = 1 - target; burn rate = error rate / budget",
                "routes": slos(rows, now)}
