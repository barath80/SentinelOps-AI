"""Source adapters: turn a raw record from any source into a NormalizedEvent.

Adding a new log source means adding one function here and registering it in ADAPTERS.
Adapters never invent data: anything they cannot map goes into `attributes` unchanged.
"""
import hashlib
import json
import re
import uuid
from datetime import datetime
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
    known = {"event_time", "service_name", "environment", "level", "message", "request_id"}
    return NormalizedEvent(
        event_id=_event_id(raw),
        tenant_id=tenant_id,
        environment=env if env in _ENVIRONMENTS else "demo",
        service_name=str(raw["service_name"]),
        event_type="log",
        event_time=_parse_time(raw["event_time"]),
        ingest_time=ingest_time,
        request_id=raw.get("request_id"),
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


Adapter = Callable[[dict[str, Any], str, datetime], NormalizedEvent]
ADAPTERS: dict[str, Adapter] = {"normalized": normalized, "shop_json": shop_json, "text": text_line}
