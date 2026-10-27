"""Source adapters: turn a raw record from any source into a NormalizedEvent.

Adding a new log source means adding one function here and registering it in ADAPTERS.
Adapters never invent data: anything they cannot map goes into `attributes` unchanged.
"""
import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from .schemas import NormalizedEvent

_NAMESPACE = uuid.UUID("5e17a0b5-0000-4000-8000-000000000000")

_LEVEL_MAP = {
    "debug": "info", "info": "info", "notice": "info",
    "warn": "warning", "warning": "warning",
    "error": "error", "err": "error", "fatal": "critical", "critical": "critical",
}
_ENVIRONMENTS = {"local", "staging", "demo", "production", "preview", "development"}


def _event_id(raw: dict[str, Any]) -> uuid.UUID:
    # Content-derived id: the same record delivered twice gets the same id.
    canonical = json.dumps(raw, sort_keys=True, default=str, separators=(",", ":"))
    return uuid.uuid5(_NAMESPACE, hashlib.sha256(canonical.encode()).hexdigest())


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("event_time must be an ISO-8601 string")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"unparseable event_time: {value!r}") from exc
    if dt.tzinfo is None:
        raise ValueError("event_time must include a timezone")
    return dt


def _severity(level: Any) -> str | None:
    return _LEVEL_MAP.get(str(level).lower()) if level is not None else None


def normalized(raw: dict[str, Any], tenant_id: str, ingest_time: datetime) -> NormalizedEvent:
    """Already in NormalizedEvent shape; the server owns tenant and ingest time."""
    data = {k: v for k, v in raw.items() if k not in {"tenant_id", "ingest_time"}}
    data.setdefault("event_id", _event_id(raw))
    return NormalizedEvent(**data, tenant_id=tenant_id, ingest_time=ingest_time)


def shop_json(raw: dict[str, Any], tenant_id: str, ingest_time: datetime) -> NormalizedEvent:
    """The structured JSON log line emitted by apps/shop-web (src/lib/log.ts)."""
    for key in ("event_time", "service_name", "message"):
        if key not in raw:
            raise ValueError(f"missing field: {key}")
    env = raw.get("environment")
    known = {"event_time", "service_name", "environment", "level", "message", "request_id", "trace_id"}
    return NormalizedEvent(
        event_id=_event_id(raw),
        tenant_id=tenant_id,
        environment=env if env in _ENVIRONMENTS else "demo",
        service_name=str(raw["service_name"]),
        event_type="log",
        event_time=_parse_time(raw["event_time"]),
        ingest_time=ingest_time,
        request_id=raw.get("request_id"),
        trace_id=raw.get("trace_id") if isinstance(raw.get("trace_id"), str) else None,
        severity=_severity(raw.get("level")),
        source_ref=f"{raw['service_name']}:{raw.get('request_id', 'no-request')}:{raw['message']}",
        attributes={"message": raw["message"], **{k: v for k, v in raw.items() if k not in known}},
    )


_TS = re.compile(r"^\s*(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s+")
_LEVEL = re.compile(r"\b(DEBUG|INFO|NOTICE|WARN(?:ING)?|ERROR|ERR|FATAL|CRITICAL)\b", re.I)
# Order matters: UUIDs and hex first, then plain numbers.
_VARIABLE_PARTS = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b0x[0-9a-f]+\b", re.I), "<hex>"),
    # Digits not glued to a preceding letter, so "250ms" collapses but "p95" and "s3" survive.
    (re.compile(r"(?<![A-Za-z_])\d+(?:\.\d+)?"), "<num>"),
]


def log_template(message: str) -> str:
    """Collapse variable tokens so repeated messages share one template (basic first pass)."""
    for pattern, token in _VARIABLE_PARTS:
        message = pattern.sub(token, message)
    return message


def text_line(raw: dict[str, Any], tenant_id: str, ingest_time: datetime) -> NormalizedEvent:
    """A free-form text log line: {"line": "...", "service_name": "...", "source": "..."}."""
    line = raw.get("line")
    service = raw.get("service_name")
    if not isinstance(line, str) or not line.strip():
        raise ValueError("line must be a non-empty string")
    if not isinstance(service, str) or not service:
        raise ValueError("service_name is required")

    ts_match = _TS.match(line)
    # Without a timestamp in the line we fall back to ingest time and record that fact.
    event_time = _parse_time(ts_match.group(1).replace(" ", "T")) if ts_match else ingest_time
    body = line[ts_match.end():] if ts_match else line
    level = _LEVEL.search(body)

    return NormalizedEvent(
        event_id=_event_id(raw),
        tenant_id=tenant_id,
        environment=raw.get("environment") if raw.get("environment") in _ENVIRONMENTS else "demo",
        service_name=service,
        event_type="log",
        event_time=event_time,
        ingest_time=ingest_time,
        severity=_severity(level.group(1)) if level else None,
        source_ref=str(raw.get("source", f"{service}:text")),
        attributes={
            "message": body.strip(),
            "template": log_template(body.strip()),
            "time_from_line": bool(ts_match),
        },
    )


_HEX = re.compile(r"^[0-9a-f]{8,64}$")
_SPAN_STATUS = {0: "unset", 1: "ok", 2: "error", "STATUS_CODE_UNSET": "unset", "STATUS_CODE_OK": "ok",
                "STATUS_CODE_ERROR": "error", "UNSET": "unset", "OK": "ok", "ERROR": "error"}
_MAX_ATTRS = 20


def _nanos(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer number of nanoseconds")
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer number of nanoseconds") from exc
    if n <= 0:
        raise ValueError(f"{name} must be positive")
    return n


def otel_span(raw: dict[str, Any], tenant_id: str, ingest_time: datetime) -> NormalizedEvent:
    """One span in OpenTelemetry's JSON shape (the fields of an OTLP span, flattened):
    {"traceId", "spanId", "parentSpanId"?, "name", "serviceName", "startTimeUnixNano",
     "endTimeUnixNano", "status": {"code"}, "attributes": {...}}"""
    trace_id, span_id = str(raw.get("traceId", "")).lower(), str(raw.get("spanId", "")).lower()
    if not _HEX.match(trace_id) or not _HEX.match(span_id):
        raise ValueError("traceId and spanId must be hex strings")
    name, service = raw.get("name"), raw.get("serviceName")
    if not isinstance(name, str) or not name or not isinstance(service, str) or not service:
        raise ValueError("name and serviceName are required")
    start, end = _nanos(raw.get("startTimeUnixNano"), "startTimeUnixNano"), _nanos(raw.get("endTimeUnixNano"), "endTimeUnixNano")
    if end < start:
        raise ValueError("span ends before it starts")
    status_raw = raw.get("status") if isinstance(raw.get("status"), dict) else {}
    status = _SPAN_STATUS.get(status_raw.get("code", 0), "unset")
    attrs = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {}
    parent = str(raw.get("parentSpanId") or "").lower() or None
    return NormalizedEvent(
        event_id=uuid.uuid5(_NAMESPACE, f"span:{trace_id}:{span_id}"),
        tenant_id=tenant_id,
        environment=raw.get("environment") if raw.get("environment") in _ENVIRONMENTS else "demo",
        service_name=service[:100],
        event_type="trace",
        event_time=datetime.fromtimestamp(start / 1e9, tz=timezone.utc),
        ingest_time=ingest_time,
        trace_id=trace_id,
        severity="error" if status == "error" else None,
        source_ref=f"trace:{trace_id}/{span_id}",
        attributes={"span_id": span_id, "parent_span_id": parent, "name": name[:120], "status": status,
                    "duration_ms": round((end - start) / 1e6, 3),
                    **{str(k)[:60]: v for k, v in list(attrs.items())[:_MAX_ATTRS] if isinstance(v, (str, int, float, bool))}},
    )


def metric_point(raw: dict[str, Any], tenant_id: str, ingest_time: datetime) -> NormalizedEvent:
    """One metric sample: {"name", "value", "timestamp", "serviceName", "labels"?}."""
    name, service, value = raw.get("name"), raw.get("serviceName"), raw.get("value")
    if not isinstance(name, str) or not re.match(r"^[a-zA-Z_:][a-zA-Z0-9_:.]{0,99}$", name):
        raise ValueError("name must be a metric name like db_query_duration_ms")
    if not isinstance(service, str) or not service:
        raise ValueError("serviceName is required")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("value must be a finite number")
    labels = raw.get("labels") if isinstance(raw.get("labels"), dict) else {}
    labels = {str(k)[:60]: str(v)[:120] for k, v in list(labels.items())[:_MAX_ATTRS]}
    return NormalizedEvent(
        event_id=_event_id(raw), tenant_id=tenant_id,
        environment=raw.get("environment") if raw.get("environment") in _ENVIRONMENTS else "demo",
        service_name=service[:100], event_type="metric", event_time=_parse_time(raw.get("timestamp")), ingest_time=ingest_time,
        source_ref=f"metric:{name}", attributes={"metric_name": name, "value": float(value), "labels": labels},
    )


Adapter = Callable[[dict[str, Any], str, datetime], NormalizedEvent]
ADAPTERS: dict[str, Adapter] = {"normalized": normalized, "shop_json": shop_json, "text": text_line,
                                "otel_span": otel_span, "metric": metric_point}
