from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class EventRow(Base):
    __tablename__ = "events"

    # Primary key is (tenant, event_id): re-delivered events are idempotent no-ops.
    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    environment: Mapped[str] = mapped_column(String(20))
    service_name: Mapped[str] = mapped_column(String(100))
    event_type: Mapped[str] = mapped_column(String(20))
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingest_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(10), nullable=True)
    source_ref: Mapped[str] = mapped_column(String(300))
    attributes: Mapped[dict] = mapped_column(JSON)
    schema_version: Mapped[int] = mapped_column()

    __table_args__ = (
        Index("ix_events_tenant_time", "tenant_id", "event_time"),
        Index("ix_events_service_time", "tenant_id", "service_name", "event_time"),
        Index("ix_events_request", "tenant_id", "request_id"),
    )


class IncidentRow(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36))
    title: Mapped[str] = mapped_column(String(200))
    severity: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="open")
    # leading_hypothesis | inconclusive: the engine abstains rather than force a winner.
    assessment: Mapped[str] = mapped_column(String(30))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    routes: Mapped[list] = mapped_column(JSON)
    summary: Mapped[dict] = mapped_column(JSON)

    __table_args__ = (Index("ix_incidents_tenant_started", "tenant_id", "started_at"),)


class HypothesisRow(Base):
    __tablename__ = "hypotheses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    cause_key: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(200))
    # A ranking heuristic, not a probability (see analysis/hypotheses.py).
    score: Mapped[float] = mapped_column(Float)
    score_version: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    next_test_id: Mapped[str] = mapped_column(String(80))
    breakdown: Mapped[dict] = mapped_column(JSON)
    # Previous scores are kept, never overwritten: [{"at", "score", "status", "reason"}].
    score_history: Mapped[list] = mapped_column(JSON, default=list)


class EvidenceRow(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    hypothesis_id: Mapped[str] = mapped_column(ForeignKey("hypotheses.id", ondelete="CASCADE"), index=True)
    relation: Mapped[str] = mapped_column(String(12))  # supports | contradicts | neutral | missing
    strength: Mapped[float] = mapped_column(Float)
    explanation: Mapped[str] = mapped_column(Text)
    # Ids of stored events this evidence was computed from; validated to exist before saving.
    source_refs: Mapped[list] = mapped_column(JSON)
    query_fingerprint: Mapped[str] = mapped_column(String(32))
    created_by: Mapped[str] = mapped_column(String(80))


class DiagnosticRunRow(Base):
    __tablename__ = "diagnostic_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    test_id: Mapped[str] = mapped_column(String(80))
    hypothesis_key: Mapped[str] = mapped_column(String(60))
    # supports | contradicts | inconclusive | no_data
    outcome: Mapped[str] = mapped_column(String(14))
    explanation: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON)
    source_refs: Mapped[list] = mapped_column(JSON)
    duration_ms: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ux_diag_incident_test", "incident_id", "test_id", unique=True),)


class ContractRow(Base):
    __tablename__ = "recovery_contracts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36))
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    action_template: Mapped[str] = mapped_column(String(60))
    environment: Mapped[str] = mapped_column(String(12))
    state: Mapped[str] = mapped_column(String(24))
    outcome: Mapped[str] = mapped_column(String(14), default="pending")  # pending|pass|fail|inconclusive
    proposed_by: Mapped[str] = mapped_column(String(100))
    contract: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TransitionRow(Base):
    """Append-only audit trail: one row per state change, never updated or deleted."""

    __tablename__ = "contract_transitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    contract_id: Mapped[str] = mapped_column(ForeignKey("recovery_contracts.id", ondelete="CASCADE"), index=True)
    from_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_state: Mapped[str] = mapped_column(String(24))
    actor: Mapped[str] = mapped_column(String(100))
    policy_version: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApprovalRow(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    contract_id: Mapped[str] = mapped_column(ForeignKey("recovery_contracts.id", ondelete="CASCADE"), index=True)
    reviewer: Mapped[str] = mapped_column(String(100))
    decision: Mapped[str] = mapped_column(String(10))  # approve | reject
    comment: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ActionRunRow(Base):
    __tablename__ = "action_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # unique: a contract's action can run at most once, even under retries
    contract_id: Mapped[str] = mapped_column(ForeignKey("recovery_contracts.id", ondelete="CASCADE"), unique=True)
    action_template: Mapped[str] = mapped_column(String(60))
    executor: Mapped[str] = mapped_column(String(30))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(14))  # succeeded | failed
    output: Mapped[dict] = mapped_column(JSON)


class VerificationRow(Base):
    __tablename__ = "verification_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    contract_id: Mapped[str] = mapped_column(ForeignKey("recovery_contracts.id", ondelete="CASCADE"), index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(14))  # pass | fail | inconclusive | pending
    reason: Mapped[str] = mapped_column(Text)
    predicates: Mapped[list] = mapped_column(JSON)


def make_session_factory(url: str, create_schema: bool = True) -> sessionmaker:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
    if create_schema:
        Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
