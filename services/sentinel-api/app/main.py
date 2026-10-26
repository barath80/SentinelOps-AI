import hmac
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite

from .adapters import ADAPTERS
from .config import Settings, get_settings
from .db import EventRow, make_session_factory
from .schemas import EventOut, IngestRequest, IngestResult


def create_app(settings: Settings | None = None) -> FastAPI:
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

    return app


def _insert_ignore_duplicates(session, rows: list[dict]) -> int:
    """Insert rows, skipping those whose (tenant_id, event_id) already exists."""
    # A batch can contain the same event twice; collapse it first so rowcount is exact.
    unique = {(r["tenant_id"], r["event_id"]): r for r in rows}.values()
    insert = (sqlite if session.bind.dialect.name == "sqlite" else postgresql).insert
    result = session.execute(insert(EventRow).values(list(unique)).on_conflict_do_nothing())
    return result.rowcount
