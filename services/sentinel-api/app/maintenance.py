"""Background upkeep: periodic analysis and data retention.

Safety: the scheduler only analyzes and (optionally) runs read-only diagnostics. It never proposes,
approves or executes a recovery action. Retention never deletes an event that an incident's
evidence or a diagnostic run cites, so every ledger claim keeps resolving to its source.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from .analysis.diagnostics import investigate
from .analysis.service import analyze
from .config import Settings
from .db import DiagnosticRunRow, EventRow, EvidenceRow, IncidentRow

log = logging.getLogger("sentinelops.maintenance")
BATCH = 500


def cited_event_ids(session: Session, tenant_id: str) -> set[str]:
    ids: set[str] = set()
    ev = select(EvidenceRow.source_refs).join(IncidentRow, IncidentRow.id == EvidenceRow.incident_id).where(IncidentRow.tenant_id == tenant_id)
    dr = select(DiagnosticRunRow.source_refs).join(IncidentRow, IncidentRow.id == DiagnosticRunRow.incident_id).where(IncidentRow.tenant_id == tenant_id)
    for refs in list(session.scalars(ev)) + list(session.scalars(dr)):
        ids.update(refs or [])
    return ids


def purge_events(session: Session, tenant_id: str, older_than: datetime, max_batches: int = 200) -> dict:
    """Delete events older than `older_than` that no stored evidence cites."""
    cited = cited_event_ids(session, tenant_id)
    deleted = kept = 0
    skip: set[str] = set()
    for _ in range(max_batches):
        rows = session.execute(
            select(EventRow.event_id).where(EventRow.tenant_id == tenant_id, EventRow.event_time < older_than)
            .order_by(EventRow.event_time).limit(BATCH + len(skip))).all()
        batch = [r[0] for r in rows if r[0] not in skip]
        if not batch:
            break
        doomed = [i for i in batch if i not in cited]
        skip.update(i for i in batch if i in cited)
        if doomed:
            session.execute(delete(EventRow).where(EventRow.tenant_id == tenant_id, EventRow.event_id.in_(doomed)))
            deleted += len(doomed)
        session.flush()
        if len(batch) < BATCH:
            break
    kept = len(skip)
    return {"deleted": deleted, "kept_because_cited": kept, "older_than": older_than.isoformat()}


def tick(sessions: sessionmaker, settings: Settings, now: datetime | None = None, *, purge: bool = False) -> dict:
    """One maintenance pass. Returns what it did (used by the scheduler and by tests)."""
    now = now or datetime.now(timezone.utc)
    out: dict = {"analyzed": 0, "investigated": 0, "purged": None}
    with sessions.begin() as s:
        ids = analyze(s, settings.default_tenant_id, now, settings.analysis_window_seconds, shadow=settings.shadow_model)
        out["analyzed"] = len(ids)
        if settings.auto_investigate:
            for i in ids:
                inc = s.get(IncidentRow, i)
                has_runs = s.scalar(select(DiagnosticRunRow.id).where(DiagnosticRunRow.incident_id == i))
                if inc and inc.status == "open" and not has_runs:
                    investigate(s, inc, budget=3)
                    out["investigated"] += 1
    if purge and settings.retention_days > 0:
        with sessions.begin() as s:
            out["purged"] = purge_events(s, settings.default_tenant_id, now - timedelta(days=settings.retention_days))
    return out


async def run_forever(sessions: sessionmaker, settings: Settings, interval: float | None = None) -> None:
    """Loop until cancelled. A failed pass is logged and the loop carries on."""
    interval = interval if interval is not None else settings.analyze_interval_seconds
    last_purge = datetime.now(timezone.utc) - timedelta(seconds=settings.purge_interval_seconds)
    while True:
        await asyncio.sleep(interval)
        due = (datetime.now(timezone.utc) - last_purge).total_seconds() >= settings.purge_interval_seconds
        try:
            result = await asyncio.to_thread(tick, sessions, settings, None, purge=due)
            if due:
                last_purge = datetime.now(timezone.utc)
            log.info("maintenance pass: %s", result)
        except Exception:  # noqa: BLE001 - the scheduler must survive any single failure
            log.exception("maintenance pass failed")
