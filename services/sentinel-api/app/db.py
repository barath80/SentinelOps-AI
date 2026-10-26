from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, String, create_engine
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


def make_session_factory(url: str) -> sessionmaker:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
