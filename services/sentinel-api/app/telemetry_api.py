"""Telemetry explorer: logs, traces and metric series straight from stored events.

Everything here is read-only and tenant-scoped. These endpoints are what makes evidence checkable:
every evidence item cites event ids, and GET /api/v1/telemetry/events/{id} returns that exact event;
a trace id opens the full span waterfall; an incident opens its own logs, traces and charts.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import select

from .analysis.detect import percentile, samples_from_rows
from .db import EventRow, IncidentRow

MAX_SERIES_MINUTES = 24 * 60


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def event_view(r: EventRow) -> dict:
    return {"event_id": r.event_id, "event_type": r.event_type, "service_name": r.service_name,
            "event_time": _aware(r.event_time).isoformat(), "severity": r.severity, "trace_id": r.trace_id,
            "request_id": r.request_id, "source_ref": r.source_ref, "attributes": r.attributes or {}}


def series(rows, start: datetime, end: datetime, bucket_s: int) -> dict:
    """Per route, per time bucket: requests, errors, error rate, p50 and p95 latency."""
    n = max(1, int((end - start).total_seconds() // bucket_s) + 1)
    buckets = [start + timedelta(seconds=i * bucket_s) for i in range(n)]
    by_route: dict[str, list[list]] = {}
    first_seen: dict[str, datetime] = {}
    for s in samples_from_rows(rows):
        if s.version and start <= s.time <= end and (s.version not in first_seen or s.time < first_seen[s.version]):
            first_seen[s.version] = s.time
        if s.route.startswith("/api/admin") or not (start <= s.time <= end):
            continue
        i = min(n - 1, int((s.time - start).total_seconds() // bucket_s))
        by_route.setdefault(s.route, [[] for _ in range(n)])[i].append(s)
    out = {}
    for route, cells in sorted(by_route.items()):
        pts = []
        for t, xs in zip(buckets, cells):
            durs = [x.duration_ms for x in xs]
            errs = sum(x.is_error for x in xs)
            pts.append({"t": t.isoformat(), "requests": len(xs), "errors": errs,
                        "throttled": sum(1 for x in xs if x.status == 429),
                        "error_rate": round(errs / len(xs), 4) if xs else None,
                        "p50_ms": percentile(durs, 50) if durs else None, "p95_ms": percentile(durs, 95) if durs else None})
        out[route] = pts
    # Release markers: the version seen first was already running; each one that appears after it is a
    # change worth drawing (the misleading-deployment case needs to be visible on the charts).
    releases = [{"t": t.isoformat(), "version": v} for v, t in sorted(first_seen.items(), key=lambda kv: kv[1])[1:]]
    return {"start": start.isoformat(), "end": end.isoformat(), "bucket_seconds": bucket_s, "routes": out, "releases": releases}


def waterfall(spans: list[EventRow]) -> list[dict]:
    """Spans of one trace ordered as a tree, each with its depth and offset from the root."""
    def start_of(sp):
        return _aware(sp.event_time)
    by_parent: dict[str | None, list[EventRow]] = {}
    ids = {(sp.attributes or {}).get("span_id") for sp in spans}
    for sp in spans:
        parent = (sp.attributes or {}).get("parent_span_id")
        by_parent.setdefault(parent if parent in ids else None, []).append(sp)
    t0 = min((start_of(sp) for sp in spans), default=None)
    out: list[dict] = []
    seen: set[str] = set()

    def walk(parent, depth):
        if depth > 50:  # malformed (cyclic or absurdly deep) span data
            return
        for sp in sorted(by_parent.get(parent, []), key=start_of):
            if sp.event_id in seen:
                continue
            seen.add(sp.event_id)
            a = sp.attributes or {}
            out.append({"event_id": sp.event_id, "span_id": a.get("span_id"), "parent_span_id": a.get("parent_span_id"),
                        "name": a.get("name"), "status": a.get("status"), "duration_ms": a.get("duration_ms"),
                        "offset_ms": round((start_of(sp) - t0).total_seconds() * 1000, 1), "depth": depth,
                        "attributes": {k: v for k, v in a.items() if k not in ("span_id", "parent_span_id", "name", "status", "duration_ms")}})
            walk(a.get("span_id"), depth + 1)
    walk(None, 0)
    return out


def register(app: FastAPI, tenant_id: str, sessions, auth) -> None:
    read = [Depends(auth.require("read"))]
    base = lambda: select(EventRow).where(EventRow.tenant_id == tenant_id)

    def window(minutes: int, until: datetime | None) -> tuple[datetime, datetime]:
        end = _aware(until) if until else datetime.now(timezone.utc)
        return end - timedelta(minutes=minutes), end

    @app.get("/api/v1/telemetry/logs", dependencies=read)
    def logs(minutes: Annotated[int, Query(ge=1, le=MAX_SERIES_MINUTES)] = 60, until: datetime | None = None,
             route: str | None = None, min_status: Annotated[int, Query(ge=0, le=599)] = 0,
             q: Annotated[str | None, Query(max_length=100)] = None, trace_id: str | None = None,
             limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[dict]:
        start, end = window(minutes, until)
        stmt = base().where(EventRow.event_type == "log", EventRow.event_time >= start, EventRow.event_time <= end)
        if trace_id:
            stmt = stmt.where(EventRow.trace_id == trace_id)
        with sessions() as s:
            rows = list(s.scalars(stmt.order_by(EventRow.event_time.desc()).limit(5000)))
        out = []
        for r in rows:
            a = r.attributes or {}
            if route and a.get("route") != route:
                continue
            if min_status and not (isinstance(a.get("status"), int) and a["status"] >= min_status):
                continue
            if q and q.lower() not in " ".join(str(v) for v in (a.get("message"), a.get("error"), a.get("route"), r.request_id)).lower():
                continue
            out.append(event_view(r))
            if len(out) >= limit:
                break
        return out

    @app.get("/api/v1/telemetry/traces", dependencies=read)
    def traces(minutes: Annotated[int, Query(ge=1, le=MAX_SERIES_MINUTES)] = 60, until: datetime | None = None,
               route: str | None = None, errors_only: bool = False, min_duration_ms: Annotated[float, Query(ge=0)] = 0,
               limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[dict]:
        """Root spans (one per request), slowest first."""
        start, end = window(minutes, until)
        with sessions() as s:
            rows = list(s.scalars(base().where(EventRow.event_type == "trace", EventRow.event_time >= start,
                                               EventRow.event_time <= end).limit(20000)))
        roots = [r for r in rows if not (r.attributes or {}).get("parent_span_id")]
        kids: dict[str, int] = {}
        for r in rows:
            if (r.attributes or {}).get("parent_span_id"):
                kids[r.trace_id] = kids.get(r.trace_id, 0) + 1
        out = []
        for r in roots:
            a = r.attributes or {}
            if route and a.get("http.route") != route:
                continue
            if errors_only and a.get("status") != "error":
                continue
            if float(a.get("duration_ms") or 0) < min_duration_ms:
                continue
            out.append({"trace_id": r.trace_id, "name": a.get("name"), "route": a.get("http.route"), "status": a.get("status"),
                        "duration_ms": a.get("duration_ms"), "cpu_ms": a.get("cpu_ms"), "spans": kids.get(r.trace_id, 0) + 1,
                        "event_time": _aware(r.event_time).isoformat()})
        return sorted(out, key=lambda x: -(x["duration_ms"] or 0))[:limit]

    @app.get("/api/v1/telemetry/traces/{trace_id}", dependencies=read)
    def trace(trace_id: str) -> dict:
        with sessions() as s:
            spans = list(s.scalars(base().where(EventRow.event_type == "trace", EventRow.trace_id == trace_id)))
            logs_ = list(s.scalars(base().where(EventRow.event_type == "log", EventRow.trace_id == trace_id)))
        if not spans and not logs_:
            raise HTTPException(status_code=404, detail="not_found")
        return {"trace_id": trace_id, "spans": waterfall(spans), "logs": [event_view(r) for r in logs_]}

    @app.get("/api/v1/telemetry/events/{event_id}", dependencies=read)
    def one_event(event_id: str) -> dict:
        with sessions() as s:
            r = s.get(EventRow, (tenant_id, event_id))
        if r is None:
            raise HTTPException(status_code=404, detail="not_found")
        return event_view(r)

    @app.get("/api/v1/telemetry/series", dependencies=read)
    def metric_series(minutes: Annotated[int, Query(ge=5, le=MAX_SERIES_MINUTES)] = 60, until: datetime | None = None,
                      bucket_seconds: Annotated[int, Query(ge=10, le=3600)] = 60) -> dict:
        start, end = window(minutes, until)
        with sessions() as s:
            rows = list(s.scalars(base().where(EventRow.event_type == "log", EventRow.event_time >= start, EventRow.event_time <= end)))
        return series(rows, start, end, bucket_seconds)

    @app.get("/api/v1/incidents/{incident_id}/telemetry", dependencies=read)
    def incident_telemetry(incident_id: str) -> dict:
        """The incident's own evidence base: charts around it, its failing requests and their traces."""
        with sessions() as s:
            inc = s.get(IncidentRow, incident_id)
            if inc is None or inc.tenant_id != tenant_id:
                raise HTTPException(status_code=404, detail="not_found")
            end = _aware(inc.detected_at)
            start = end - timedelta(seconds=(inc.summary or {}).get("analysis_window_seconds") or 900)
            rows = list(s.scalars(base().where(EventRow.event_time >= start, EventRow.event_time <= end)))
        mine = set(inc.routes)
        logs_ = [r for r in rows if r.event_type == "log" and (r.attributes or {}).get("route") in mine]
        onset = _aware(inc.started_at)
        # "Unusual" = failed, an error-type log line, or slower than 2x the route's baseline p95.
        slow_cut = {a["route"]: max(2 * a["baseline_p95_ms"], a["baseline_p95_ms"] + 200)
                    for a in (inc.summary or {}).get("anomalies", []) if a.get("baseline_p95_ms")}

        def unusual(r) -> bool:
            a = r.attributes or {}
            return ((a.get("status") or 0) >= 500 or a.get("message") not in ("request",)
                    or (isinstance(a.get("duration_ms"), (int, float)) and a["duration_ms"] >= slow_cut.get(a.get("route"), float("inf"))))
        bad = [r for r in logs_ if _aware(r.event_time) >= onset - timedelta(seconds=5) and unusual(r)]
        slow_traces = sorted({r.trace_id for r in logs_ if r.trace_id and _aware(r.event_time) >= onset - timedelta(seconds=5)})
        roots = {r.trace_id: r for r in rows if r.event_type == "trace" and not (r.attributes or {}).get("parent_span_id")}
        candidates = sorted((roots[t] for t in slow_traces if t in roots),
                            key=lambda r: -float((r.attributes or {}).get("duration_ms") or 0))[:10]
        bucket = max(10, int((end - start).total_seconds() // 30))  # about 30 points per chart
        return {"series": series([r for r in rows if r.event_type == "log"], start, end, bucket),
                "onset": onset.isoformat(),
                "failing_logs": [event_view(r) for r in sorted(bad, key=lambda r: _aware(r.event_time))[-50:]],
                "traces": [{"trace_id": r.trace_id, "route": (r.attributes or {}).get("http.route"),
                            "duration_ms": (r.attributes or {}).get("duration_ms"), "status": (r.attributes or {}).get("status")}
                           for r in candidates]}
