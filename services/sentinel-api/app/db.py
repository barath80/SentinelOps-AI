from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """Timestamps are always UTC and always come back timezone-aware. SQLite stores them without a
    zone, so without this an API response carried a bare "07:57" that browsers read as local time."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        # naive means UTC; an aware value in another zone is converted, never just relabelled
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


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
    event_time: Mapped[datetime] = mapped_column(UTCDateTime())
    ingest_time: Mapped[datetime] = mapped_column(UTCDateTime())
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
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime())
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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())

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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


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
    at: Mapped[datetime] = mapped_column(UTCDateTime())


class ApprovalRow(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    contract_id: Mapped[str] = mapped_column(ForeignKey("recovery_contracts.id", ondelete="CASCADE"), index=True)
    reviewer: Mapped[str] = mapped_column(String(100))
    decision: Mapped[str] = mapped_column(String(10))  # approve | reject
    comment: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(UTCDateTime())


class ActionRunRow(Base):
    __tablename__ = "action_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # unique: a contract's action can run at most once, even under retries
    contract_id: Mapped[str] = mapped_column(ForeignKey("recovery_contracts.id", ondelete="CASCADE"), unique=True)
    action_template: Mapped[str] = mapped_column(String(60))
    executor: Mapped[str] = mapped_column(String(30))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    status: Mapped[str] = mapped_column(String(14))  # succeeded | failed
    output: Mapped[dict] = mapped_column(JSON)


class RehearsalRow(Base):
    """A counterfactual replay of the contract's action on recorded telemetry. Simulation evidence only."""

    __tablename__ = "rehearsal_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    contract_id: Mapped[str] = mapped_column(ForeignKey("recovery_contracts.id", ondelete="CASCADE"), index=True)
    model_version: Mapped[str] = mapped_column(String(20))
    outcome: Mapped[str] = mapped_column(String(14))  # pass | fail | inconclusive
    reason: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON)
    requested_by: Mapped[str] = mapped_column(String(100))
    at: Mapped[datetime] = mapped_column(UTCDateTime())


class RollbackRunRow(Base):
    __tablename__ = "rollback_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # unique: a contract is rolled back at most once
    contract_id: Mapped[str] = mapped_column(ForeignKey("recovery_contracts.id", ondelete="CASCADE"), unique=True)
    rollback_template: Mapped[str] = mapped_column(String(60))
    executor: Mapped[str] = mapped_column(String(30))
    requested_by: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    status: Mapped[str] = mapped_column(String(14))  # running | succeeded | failed
    output: Mapped[dict] = mapped_column(JSON)


class VerificationRow(Base):
    __tablename__ = "verification_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    contract_id: Mapped[str] = mapped_column(ForeignKey("recovery_contracts.id", ondelete="CASCADE"), index=True)
    window_start: Mapped[datetime] = mapped_column(UTCDateTime())
    window_end: Mapped[datetime] = mapped_column(UTCDateTime())
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    outcome: Mapped[str] = mapped_column(String(14))  # pass | fail | inconclusive | pending
    reason: Mapped[str] = mapped_column(Text)
    predicates: Mapped[list] = mapped_column(JSON)


class IncidentLabelRow(Base):
    """A person's judgement of an incident's true cause: ground truth for evaluating the models."""

    __tablename__ = "incident_labels"

    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True)
    label: Mapped[str] = mapped_column(String(40))
    labeled_by: Mapped[str] = mapped_column(String(100))
    note: Mapped[str] = mapped_column(Text, default="")
    labeled_at: Mapped[datetime] = mapped_column(UTCDateTime())


class OperatorRow(Base):
    """A person who can log in to SentinelOps. Passwords are scrypt hashes, never stored in clear."""

    __tablename__ = "operators"

    username: Mapped[str] = mapped_column(String(100), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(12))  # viewer | responder | approver | admin
    disabled: Mapped[bool] = mapped_column(default=False)
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    # Sessions issued before this moment are invalid (logout, password change, disabling).
    sessions_valid_after: Mapped[datetime] = mapped_column(UTCDateTime())
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class PreventionArtifactRow(Base):
    """A proposed regression test / alert rule / runbook change. Text only: never executed or merged."""

    __tablename__ = "prevention_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    contract_id: Mapped[str] = mapped_column(String(36))
    artifact_type: Mapped[str] = mapped_column(String(24))  # regression_test|alert_rule|runbook_amendment|monitoring_gap
    title: Mapped[str] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(12))
    content: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[list] = mapped_column(JSON)
    source_event_ids: Mapped[list] = mapped_column(JSON)
    review_status: Mapped[str] = mapped_column(String(10), default="proposed")  # proposed|approved|rejected
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    checks: Mapped[list] = mapped_column(JSON)
    checks_passed: Mapped[bool] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


def make_session_factory(url: str, create_schema: bool = True) -> sessionmaker:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
    if create_schema:
        Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


class AuditRow(Base):
    """Append-only record of security-relevant changes (operators, channels, policies, automation)."""

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(60))
    target: Mapped[str] = mapped_column(String(200), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class NotificationChannelRow(Base):
    __tablename__ = "notification_channels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(12))  # slack | webhook
    url: Mapped[str] = mapped_column(Text)  # never returned by the API, only its host
    signing_secret: Mapped[str] = mapped_column(String(100))  # HMAC key for X-SentinelOps-Signature
    events: Mapped[list] = mapped_column(JSON)  # event types delivered to this channel
    enabled: Mapped[bool] = mapped_column(default=True)
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class NotificationRow(Base):
    """Outbox: written in the same transaction as the change it reports, sent afterwards."""

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    channel_id: Mapped[str] = mapped_column(ForeignKey("notification_channels.id", ondelete="CASCADE"), index=True)
    event: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | sent | failed
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime())
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class AutomationPolicyRow(Base):
    """How much SentinelOps may do on its own for one cause. The default for every cause is manual."""

    __tablename__ = "automation_policies"

    cause_key: Mapped[str] = mapped_column(String(60), primary_key=True)
    mode: Mapped[str] = mapped_column(String(10))  # manual | propose | auto
    auto_rollback: Mapped[bool] = mapped_column(default=True)
    max_risk: Mapped[str] = mapped_column(String(10), default="low")  # low | medium
    updated_by: Mapped[str] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class AutomationRunRow(Base):
    __tablename__ = "automation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    incident_id: Mapped[str] = mapped_column(String(36), index=True)
    contract_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    step: Mapped[str] = mapped_column(String(20))  # propose | execute | verify | rollback | skip
    outcome: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text, default="")
