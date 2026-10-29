from datetime import datetime, timedelta, timezone
from typing import Annotated

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite

from .adapters import ADAPTERS
from .config import Settings, get_settings
from . import audit, auth as auth_mod, automation, insights, maintenance, notify, overview, prevention, ratelimit, telemetry_api
from .analysis import quality
from .analysis.diagnostics import TESTS, investigate, investigated_answer, run_test
from .analysis.service import analyze
from .db import DiagnosticRunRow, EventRow, EvidenceRow, IncidentLabelRow, HypothesisRow, IncidentRow, make_session_factory
from .recovery import api as recovery_api
from .recovery.executors import Executor, MockExecutor, ShopAdminExecutor
from .schemas import LabelRequest, DiagnosticRequest, DiagnosticRunOut, InvestigateRequest, EventOut, EvidenceOut, HypothesisOut, IncidentOut, IngestRequest, IngestResult


def create_app(settings: Settings | None = None, executor: Executor | None = None) -> FastAPI:
    settings = settings or get_settings()
    sessions = make_session_factory(settings.database_url, settings.auto_create_schema)
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        tasks = [asyncio.create_task(notify_loop())]  # delivers queued team notifications
        if settings.analyze_interval_seconds > 0:  # off by default; serverless hosts should not enable it
            tasks.append(asyncio.create_task(maintenance.run_forever(sessions, settings, executor=executor)))
        yield
        for task in tasks:
            task.cancel()

    async def notify_loop():
        while True:
            await asyncio.sleep(settings.notify_interval_seconds)
            try:
                await asyncio.to_thread(notify.flush, sessions, settings.notify_allow_private, settings.notify_allow_private)
            except Exception:  # noqa: BLE001 - delivery problems are recorded per row; the loop must survive
                logging.getLogger("sentinelops.notify").exception("notification flush failed")

    app = FastAPI(title="SentinelOps API", version="0.3.0", lifespan=lifespan)
    app.state.sessions, app.state.settings = sessions, settings
    # Fails closed: no ingest token means no machine access, no session secret means no logins.
    auth = auth_mod.Auth(settings, sessions)
    auth_mod.bootstrap(sessions, settings)
    auth.register(app)
    READ, ANALYZE = [Depends(auth.require("read"))], [Depends(auth.require("analyze"))]

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        # The API has no page of its own; send people to the dashboard.
        return RedirectResponse("/ui/", status_code=307)

    @app.post("/api/v1/telemetry/events", response_model=IngestResult, dependencies=[Depends(auth.require("ingest"))])
    async def ingest(
        request: Request,
        adapter: Annotated[str, Query(description="Source adapter name")] = "normalized",
    ) -> IngestResult:
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > settings.max_body_bytes:
            raise HTTPException(status_code=413, detail="body_too_large")
        raw_body = await request.body()
        if len(raw_body) > settings.max_body_bytes:
            raise HTTPException(status_code=413, detail="body_too_large")
        try:
            payload = IngestRequest.model_validate_json(raw_body)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail="invalid_body") from exc
        if len(payload.events) > settings.max_batch_events:
            raise HTTPException(status_code=413, detail="too_many_events")
        convert = ADAPTERS.get(adapter)
        if convert is None:
            raise HTTPException(status_code=400, detail=f"unknown_adapter: {adapter}")

        now = datetime.now(timezone.utc)
        latest_allowed = now + timedelta(seconds=settings.max_future_skew_seconds)
        rows: list[dict] = []
        errors: list[dict] = []
        for index, raw in enumerate(payload.events):
            try:
                event = convert(raw, settings.default_tenant_id, now)
                if event.event_time > latest_allowed:
                    raise ValueError("event_time is too far in the future (clock skew?)")
            except (ValueError, ValidationError) as exc:
                errors.append({"index": index, "error": str(exc).splitlines()[0][:200]})
                continue
            row = event.model_dump()
            row["event_id"] = str(event.event_id)
            row["tenant_id"] = str(event.tenant_id)
            rows.append(row)

        accepted = 0
        if rows:
            with sessions.begin() as session:
                accepted = _insert_ignore_duplicates(session, rows)
        return IngestResult(accepted=accepted, duplicates=len(rows) - accepted, rejected=len(errors), errors=errors[:20])

    @app.get("/api/v1/telemetry/events", response_model=list[EventOut], dependencies=READ)
    def list_events(
        service: str | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> list[EventOut]:
        stmt = (
            select(EventRow)
            .where(EventRow.tenant_id == settings.default_tenant_id)
            .order_by(EventRow.event_time.desc())
            .limit(limit)
        )
        if service:
            stmt = stmt.where(EventRow.service_name == service)
        with sessions() as session:
            return [EventOut.model_validate(r, from_attributes=True) for r in session.scalars(stmt)]

    @app.get("/api/v1/telemetry/quality", dependencies=READ)
    def telemetry_quality(window_seconds: Annotated[int, Query(ge=60, le=86400)] = 900) -> dict:
        """Clock-skew check over recently stamped events (scenario S11)."""
        now = datetime.now(timezone.utc)
        stmt = select(EventRow).where(EventRow.tenant_id == settings.default_tenant_id,
                                      EventRow.event_time >= now - timedelta(seconds=window_seconds),
                                      EventRow.event_time <= now + timedelta(seconds=settings.max_future_skew_seconds))
        with sessions() as session:
            return {"window_seconds": window_seconds, "as_of": now.isoformat(), **quality.assess(list(session.scalars(stmt)))}

    def load_incident(session, inc: IncidentRow) -> IncidentOut:
        hyps = list(session.scalars(select(HypothesisRow).where(HypothesisRow.incident_id == inc.id).order_by(HypothesisRow.score.desc())))
        ev = list(session.scalars(select(EvidenceRow).where(EvidenceRow.incident_id == inc.id)))
        out = IncidentOut.model_validate(inc, from_attributes=True)
        for h in hyps:
            ho = HypothesisOut.model_validate(h, from_attributes=True)
            ho.evidence = [EvidenceOut.model_validate(e, from_attributes=True) for e in ev if e.hypothesis_id == h.id]
            out.hypotheses.append(ho)
        for d in session.scalars(select(DiagnosticRunRow).where(DiagnosticRunRow.incident_id == inc.id).order_by(DiagnosticRunRow.created_at)):
            out.diagnostic_runs.append(DiagnosticRunOut.model_validate(d, from_attributes=True))
        lab = session.get(IncidentLabelRow, inc.id)
        if lab:
            out.label = {"label": lab.label, "labeled_by": lab.labeled_by, "note": lab.note, "labeled_at": lab.labeled_at.isoformat()}
        return out

    def own_incident(session, incident_id: str) -> IncidentRow:
        inc = session.get(IncidentRow, incident_id)
        if inc is None or inc.tenant_id != settings.default_tenant_id:
            raise HTTPException(status_code=404, detail="not_found")
        return inc

    @app.post("/api/v1/maintenance/purge", dependencies=[Depends(auth.require("admin"))])
    def purge(days: Annotated[int, Query(ge=0, le=3650, description="Delete events older than this; 0 = the configured retention")] = 0) -> dict:
        keep_days = days or settings.retention_days
        with sessions.begin() as session:
            return maintenance.purge_events(session, settings.default_tenant_id,
                                            datetime.now(timezone.utc) - timedelta(days=keep_days))

    @app.post("/api/v1/incidents/{incident_id}/diagnostics", response_model=IncidentOut, dependencies=ANALYZE)
    def run_diagnostic(incident_id: str, body: DiagnosticRequest) -> IncidentOut:
        if body.test_id not in TESTS:  # allow-list: unknown ids are rejected, never interpreted
            raise HTTPException(status_code=400, detail=f"unknown_test: {body.test_id}")
        with sessions.begin() as session:
            inc = own_incident(session, incident_id)
            run_test(session, inc, body.test_id)
            return load_incident(session, inc)

    @app.post("/api/v1/incidents/{incident_id}/label")
    def label_incident(incident_id: str, body: LabelRequest, who: Annotated[str, Depends(auth.actor("act"))]) -> IncidentOut:
        with sessions.begin() as session:
            inc = own_incident(session, incident_id)
            row = session.get(IncidentLabelRow, inc.id)
            if row is None:
                row = IncidentLabelRow(incident_id=inc.id)
                session.add(row)
            row.label, row.labeled_by, row.note = body.label, who, body.note
            row.labeled_at = datetime.now(timezone.utc)
            session.flush()
            return load_incident(session, inc)

    @app.get("/api/v1/training/labelled", dependencies=READ)
    def labelled() -> list[dict]:
        """Labelled incidents with the features the model sees: an evaluation set from real traffic."""
        with sessions() as session:
            q = (select(IncidentLabelRow, IncidentRow).join(IncidentRow, IncidentRow.id == IncidentLabelRow.incident_id)
                 .where(IncidentRow.tenant_id == settings.default_tenant_id).order_by(IncidentLabelRow.labeled_at))
            out = []
            for lab, inc in session.execute(q):
                shadow = (inc.summary or {}).get("shadow_model") or {}
                # The answer after the read-only investigation, if one ran (it can differ from rule_answer).
                investigated = investigated_answer(session, inc)
                containment = ((inc.summary or {}).get("propagation") or {}).get("earliest_containment") or {}
                out.append({"incident_id": inc.id, "label": lab.label, "labeled_by": lab.labeled_by, "labeled_at": lab.labeled_at.isoformat(),
                            "note": lab.note, "started_at": inc.started_at.isoformat(), "title": inc.title,
                            "features": (inc.summary or {}).get("model_features"), "rule_answer": (inc.summary or {}).get("rule_answer"),
                            "investigated_answer": investigated, "containment": containment.get("node"),
                            "shadow_prediction": shadow.get("prediction"), "shadow_version": shadow.get("version")})
            return out

    @app.get("/api/v1/shadow/report", dependencies=READ)
    def shadow_report() -> dict:
        """How often the shadow model agrees with the rule engine, and with human labels."""
        with sessions() as session:
            incs = list(session.scalars(select(IncidentRow).where(IncidentRow.tenant_id == settings.default_tenant_id)))
            labels = {l.incident_id: l.label for l in session.scalars(select(IncidentLabelRow).where(
                IncidentLabelRow.incident_id.in_([i.id for i in incs] or [""])))}
        with_shadow = [i for i in incs if (i.summary or {}).get("shadow_model")]
        agree = sum(1 for i in with_shadow if i.summary["shadow_model"].get("agrees_with_rules"))
        judged = [i for i in with_shadow if i.id in labels]
        model_ok = sum(1 for i in judged if i.summary["shadow_model"]["prediction"] == labels[i.id])
        rules_ok = sum(1 for i in judged if i.summary.get("rule_answer") == labels[i.id])
        return {"incidents": len(incs), "with_shadow_prediction": len(with_shadow),
                "agreement_with_rules": round(agree / len(with_shadow), 3) if with_shadow else None,
                "labelled": len(judged),
                "model_correct": model_ok, "rules_correct": rules_ok,
                "model_accuracy": round(model_ok / len(judged), 3) if judged else None,
                "rules_accuracy": round(rules_ok / len(judged), 3) if judged else None,
                "note": "Shadow predictions are recorded only; they never change rankings, recommendations or actions."}

    @app.post("/api/v1/incidents/{incident_id}/investigate", dependencies=ANALYZE)
    def run_investigation(incident_id: str, body: InvestigateRequest | None = None) -> dict:
        with sessions.begin() as session:
            inc = own_incident(session, incident_id)
            report = investigate(session, inc, (body or InvestigateRequest()).budget)
            return {"report": report, "incident": load_incident(session, inc).model_dump(mode="json")}

    @app.post("/api/v1/incidents/analyze", response_model=list[IncidentOut], dependencies=ANALYZE)
    def run_analysis(
        window_seconds: Annotated[int, Query(ge=60, le=86400)] = 900,
        as_of: Annotated[datetime | None, Query(description="Analyze as of this time (default: now)")] = None,
    ) -> list[IncidentOut]:
        when = as_of or datetime.now(timezone.utc)
        if when.tzinfo is None:
            raise HTTPException(status_code=422, detail="as_of must include a timezone")
        with sessions.begin() as session:
            ids = analyze(session, settings.default_tenant_id, when, window_seconds, shadow=settings.shadow_model)
            incidents = [session.get(IncidentRow, i) for i in ids]
            return [load_incident(session, i) for i in incidents if i]

    @app.get("/api/v1/incidents", response_model=list[IncidentOut], dependencies=READ)
    def list_incidents(limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[IncidentOut]:
        stmt = (select(IncidentRow).where(IncidentRow.tenant_id == settings.default_tenant_id)
                .order_by(IncidentRow.started_at.desc()).limit(limit))
        with sessions() as session:
            return [load_incident(session, i) for i in session.scalars(stmt)]

    @app.get("/api/v1/incidents/{incident_id}", response_model=IncidentOut, dependencies=READ)
    def get_incident(incident_id: str) -> IncidentOut:
        with sessions() as session:
            inc = session.get(IncidentRow, incident_id)
            # Tenant check on every read: another tenant's id looks like "not found".
            if inc is None or inc.tenant_id != settings.default_tenant_id:
                raise HTTPException(status_code=404, detail="not_found")
            return load_incident(session, inc)

    if executor is None:
        executor = (ShopAdminExecutor(settings.shop_admin_url, settings.shop_admin_token)
                    if settings.executor == "shop_admin" else MockExecutor())
    app.state.executor = executor
    recovery_api.register(app, settings, sessions, auth, executor)
    prevention.register(app, settings.default_tenant_id, sessions, auth)
    notify.PUBLIC_URL = settings.public_url
    telemetry_api.register(app, settings.default_tenant_id, sessions, auth)
    audit.register(app, settings.default_tenant_id, sessions, auth)
    notify.register(app, settings, sessions, auth)
    automation.register(app, settings, sessions, auth, executor)
    overview.register(app, settings, sessions, auth)
    insights.register(app, settings.default_tenant_id, sessions, auth)

    # Dashboard: static files served same-origin. The CSP forbids inline script and any outside host.
    app.mount("/ui", StaticFiles(directory=Path(__file__).parent / "ui", html=True), name="ui")

    app.middleware("http")(ratelimit.middleware(settings))

    @app.middleware("http")
    async def ui_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        if request.url.path.startswith("/ui"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Cache-Control"] = "no-store"
        return response

    return app


def _insert_ignore_duplicates(session, rows: list[dict]) -> int:
    """Insert rows, skipping those whose (tenant_id, event_id) already exists."""
    # A batch can contain the same event twice; collapse it first so rowcount is exact.
    unique = {(r["tenant_id"], r["event_id"]): r for r in rows}.values()
    insert = (sqlite if session.bind.dialect.name == "sqlite" else postgresql).insert
    # Count the rows actually inserted via RETURNING: Postgres drivers report rowcount -1 for
    # multi-row inserts, which made the "accepted" figure wrong there (SQLite happened to work).
    stmt = insert(EventRow).values(list(unique)).on_conflict_do_nothing().returning(EventRow.event_id)
    return len(session.execute(stmt).all())
