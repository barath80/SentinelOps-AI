from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

Environment = Literal["local", "staging", "demo", "production", "preview", "development"]
EventType = Literal["metric", "log", "trace", "deployment", "config", "alert"]
Severity = Literal["info", "warning", "error", "critical"]


class NormalizedEvent(BaseModel):
    """Common shape every source is converted into (blueprint section 6.2)."""

    event_id: UUID
    tenant_id: UUID
    environment: Environment
    service_name: str = Field(min_length=1, max_length=100)
    event_type: EventType
    event_time: AwareDatetime
    ingest_time: AwareDatetime
    trace_id: str | None = Field(default=None, max_length=100)
    request_id: str | None = Field(default=None, max_length=100)
    severity: Severity | None = None
    source_ref: str = Field(min_length=1, max_length=300)
    attributes: dict[str, Any] = Field(default_factory=dict)
    schema_version: int = 1


class IngestRequest(BaseModel):
    events: list[dict[str, Any]]


class IngestResult(BaseModel):
    accepted: int
    duplicates: int
    rejected: int
    errors: list[dict[str, Any]] = Field(default_factory=list)


class EventOut(BaseModel):
    event_id: UUID
    service_name: str
    event_type: EventType
    event_time: datetime
    ingest_time: datetime
    severity: Severity | None
    request_id: str | None
    attributes: dict[str, Any]


class EvidenceOut(BaseModel):
    id: str
    hypothesis_id: str
    relation: Literal["supports", "contradicts", "neutral", "missing"]
    strength: float
    explanation: str
    source_refs: list[str]
    query_fingerprint: str
    created_by: str


class HypothesisOut(BaseModel):
    id: str
    cause_key: str
    title: str
    score: float
    score_version: str
    score_is_probability: bool = False
    status: str
    next_test_id: str
    breakdown: dict[str, Any]
    score_history: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[EvidenceOut] = Field(default_factory=list)


class DiagnosticRunOut(BaseModel):
    id: str
    test_id: str
    hypothesis_key: str
    outcome: str
    explanation: str
    details: dict[str, Any]
    source_refs: list[str]
    duration_ms: int
    created_at: datetime


class DiagnosticRequest(BaseModel):
    test_id: str


class InvestigateRequest(BaseModel):
    budget: int = Field(default=3, ge=1, le=6)


class IncidentOut(BaseModel):
    id: str
    title: str
    severity: str
    status: str
    assessment: str
    started_at: datetime
    detected_at: datetime
    routes: list[str]
    summary: dict[str, Any]
    hypotheses: list[HypothesisOut] = Field(default_factory=list)
    diagnostic_runs: list[DiagnosticRunOut] = Field(default_factory=list)
