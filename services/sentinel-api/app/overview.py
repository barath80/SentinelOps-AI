"""Overview and model endpoints: the dashboard's home page and the learned model's own page."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import func, select

from . import automation
from .analysis import learned, quality, throttle
from .analysis.detect import percentile, samples_from_rows
from .analysis.diagnostics import investigated_answer
from .db import ContractRow, EventRow, IncidentRow, NotificationRow

MODEL_META = Path(__file__).resolve().parent.parent / "models" / "root_cause_v2.json"


def register(app: FastAPI, settings, sessions, auth) -> None:
    read = auth.require("read")
    tenant = settings.default_tenant_id

    @app.get("/api/v1/overview")
    def overview(_p: Annotated[object, Depends(read)]) -> dict:
        now = datetime.now(timezone.utc)
        with sessions() as s:
            rows = list(s.scalars(select(EventRow).where(EventRow.tenant_id == tenant, EventRow.event_time >= now - timedelta(minutes=15),
                                                         EventRow.event_time <= now + timedelta(minutes=5))))
            open_by_sev = dict(s.execute(select(IncidentRow.severity, func.count()).where(
                IncidentRow.tenant_id == tenant, IncidentRow.status == "open").group_by(IncidentRow.severity)).all())
            waiting = s.scalar(select(func.count()).select_from(ContractRow).where(
                ContractRow.tenant_id == tenant, ContractRow.state == "AWAITING_APPROVAL")) or 0
            verifying = s.scalar(select(func.count()).select_from(ContractRow).where(
                ContractRow.tenant_id == tenant, ContractRow.state == "VERIFYING")) or 0
            failed_notes = s.scalar(select(func.count()).select_from(NotificationRow).where(
                NotificationRow.status == "failed", NotificationRow.created_at >= now - timedelta(days=1))) or 0
            auto_on = automation.is_on(s, settings)
        samples = [x for x in samples_from_rows([r for r in rows if r.event_type == "log"]) if x.time <= now]
        routes = []
        for route in sorted({x.route for x in samples if not x.route.startswith("/api/admin")}):
            xs = [x for x in samples if x.route == route]
            err = sum(x.is_error for x in xs) / len(xs)
            p95 = percentile([x.duration_ms for x in xs], 95)
            routes.append({"route": route, "requests": len(xs), "error_rate": round(err, 4), "p95_ms": p95,
                           "throttled": sum(1 for x in xs if x.status == 429),
                           "health": "degraded" if err >= 0.05 else "ok"})
        model = learned.load()
        return {"as_of": now.isoformat(), "window_minutes": 15, "routes": routes,
                "events_last_15_min": len(rows),
                "open_incidents": {"total": sum(open_by_sev.values()), "by_severity": open_by_sev},
                "contracts": {"awaiting_approval": waiting, "verifying": verifying},
                "automation": {"enabled": auto_on, "allowed": settings.automation_allowed},
                "telemetry_quality": quality.assess(rows)["status"],
                "throttling": throttle.assess(samples, now),
                "notifications_failed_24h": failed_notes,
                "model": model.version if model else None}

    @app.get("/api/v1/models")
    def models(_p: Annotated[object, Depends(read)]) -> dict:
        m = learned.load()
        if m is None:
            raise HTTPException(status_code=404, detail="no_model")
        meta = json.loads(MODEL_META.read_text(encoding="utf-8")) if MODEL_META.exists() else {}
        return {"serving": {"version": m.version, "algorithm": "logistic_regression", "classes": m.classes,
                            "features": m.features, "tau": m.tau, "mode": "shadow: recorded only, never used for decisions"},
                "research_model": {k: meta.get(k) for k in ("version", "algorithm", "best_params", "calibration", "tau",
                                                            "test_results", "data")} if meta else None}

    @app.get("/api/v1/incidents/{incident_id}/model")
    def incident_model(incident_id: str, _p: Annotated[object, Depends(read)]) -> dict:
        with sessions() as s:
            inc = s.get(IncidentRow, incident_id)
            if inc is None or inc.tenant_id != tenant:
                raise HTTPException(status_code=404, detail="not_found")
            summary = inc.summary or {}
            investigated = investigated_answer(s, inc)
        m, feats = learned.load(), summary.get("model_features") or {}
        if m is None or not feats or any(f not in feats for f in m.features):
            return {"available": False, "reason": "no model, or features recorded by an older model version"}
        pred = m.predict(feats)
        return {"available": True, **pred, "rule_answer": summary.get("rule_answer"), "investigated_answer": investigated,
                "explanation": m.explain(feats, pred["top_class"]),
                "note": "Contributions to the top class's score (coefficient x standardized feature). Shadow mode only."}
