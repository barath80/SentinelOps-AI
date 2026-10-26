import hmac
from datetime import datetime, timedelta, timezone
from typing import Annotated

from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite

from .adapters import ADAPTERS
from .config import Settings, get_settings
from .analysis.diagnostics import TESTS, investigate, run_test
from .analysis.service import analyze
from .db import DiagnosticRunRow, EventRow, EvidenceRow, HypothesisRow, IncidentRow, make_session_factory
from .recovery import api as recovery_api
from .recovery.executors import Executor, MockExecutor, ShopAdminExecutor
from .schemas import DiagnosticRequest, DiagnosticRunOut, InvestigateRequest, EventOut, EvidenceOut, HypothesisOut, IncidentOut, IngestRequest, IngestResult


def create_app(settings: Settings | None = None, executor: Executor | None = None) -> FastAPI:
    settings = settings or get_settings()
    sessions = make_session_factory(settings.database_url)
    app = FastAPI(title="SentinelOps API", version="0.1.0")

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = settings.ingest_token
        supplied = (authorization or "").removeprefix("Bearer ").strip()
        # Fail closed when no token is configured; constant-time compare otherwise.
        if not expected or not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="invalid_token")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/telemetry/events", response_model=IngestResult, dependencies=[Depends(require_token)])
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

    @app.get("/api/v1/telemetry/events", response_model=list[EventOut], dependencies=[Depends(require_token)])
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
        return out

    def own_incident(session, incident_id: str) -> IncidentRow:
        inc = session.get(IncidentRow, incident_id)
        if inc is None or inc.tenant_id != settings.default_tenant_id:
            raise HTTPException(status_code=404, detail="not_found")
        return inc

    @app.post("/api/v1/incidents/{incident_id}/diagnostics", response_model=IncidentOut, dependencies=[Depends(require_token)])
    def run_diagnostic(incident_id: str, body: DiagnosticRequest) -> IncidentOut:
        if body.test_id not in TESTS:  # allow-list: unknown ids are rejected, never interpreted
            raise HTTPException(status_code=400, detail=f"unknown_test: {body.test_id}")
        with sessions.begin() as session:
            inc = own_incident(session, incident_id)
            run_test(session, inc, body.test_id)
            return load_incident(session, inc)

    @app.post("/api/v1/incidents/{incident_id}/investigate", dependencies=[Depends(require_token)])
    def run_investigation(incident_id: str, body: InvestigateRequest | None = None) -> dict:
        with sessions.begin() as session:
            inc = own_incident(session, incident_id)
            report = investigate(session, inc, (body or InvestigateRequest()).budget)
            return {"report": report, "incident": load_incident(session, inc).model_dump(mode="json")}

    @app.post("/api/v1/incidents/analyze", response_model=list[IncidentOut], dependencies=[Depends(require_token)])
    def run_analysis(
        window_seconds: Annotated[int, Query(ge=60, le=86400)] = 900,
        as_of: Annotated[datetime | None, Query(description="Analyze as of this time (default: now)")] = None,
    ) -> list[IncidentOut]:
        when = as_of or datetime.now(timezone.utc)
        if when.tzinfo is None:
            raise HTTPException(status_code=422, detail="as_of must include a timezone")
        with sessions.begin() as session:
            ids = analyze(session, settings.default_tenant_id, when, window_seconds)
            incidents = [session.get(IncidentRow, i) for i in ids]
            return [load_incident(session, i) for i in incidents if i]

    @app.get("/api/v1/incidents", response_model=list[IncidentOut], dependencies=[Depends(require_token)])
    def list_incidents(limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[IncidentOut]:
        stmt = (select(IncidentRow).where(IncidentRow.tenant_id == settings.default_tenant_id)
                .order_by(IncidentRow.started_at.desc()).limit(limit))
        with sessions() as session:
            return [load_incident(session, i) for i in session.scalars(stmt)]

    @app.get("/api/v1/incidents/{incident_id}", response_model=IncidentOut, dependencies=[Depends(require_token)])
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
    recovery_api.register(app, settings, sessions, require_token, executor)

    # Dashboard: static files served same-origin. The CSP forbids inline script and any outside host.
    app.mount("/ui", StaticFiles(directory=Path(__file__).parent / "ui", html=True), name="ui")

    @app.middleware("http")
    async def ui_security_headers(request: Request, call_next):
        response = await call_next(request)
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
    result = session.execute(insert(EventRow).values(list(unique)).on_conflict_do_nothing())
    return result.rowcount
