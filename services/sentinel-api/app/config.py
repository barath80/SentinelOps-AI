from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SENTINEL_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./sentinel.db"
    @field_validator("database_url")
    @classmethod
    def _use_psycopg3(cls, url: str) -> str:
        # Hosts such as Neon hand out plain "postgresql://" or "postgres://" URLs; SQLAlchemy would
        # pick the old psycopg2 driver for those, so name the driver we ship.
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    # Bearer token accepted on ingest. Empty means "reject everything": there is no
    # open default, so a missing secret fails closed.
    ingest_token: str = ""
    # Single-tenant MVP: all ingested events belong to this tenant.
    default_tenant_id: str = "00000000-0000-0000-0000-000000000001"
    # Create missing tables at startup. Turn off on serverless/cold-start hosts and run
    # `python -m app.migrate` once instead. NOTE: this never alters existing tables.
    auto_create_schema: bool = True
    max_batch_events: int = 500
    max_body_bytes: int = 1_000_000
    max_future_skew_seconds: int = 300
    # Recovery actions: "mock" records the call only; "shop_admin" drives the demo shop's fault toggle.
    executor: str = "mock"
    shop_admin_url: str = ""
    shop_admin_token: str = ""
    default_environment: str = "demo"
    # Background upkeep (see app/maintenance.py). 0 turns the periodic analyzer off.
    analyze_interval_seconds: int = 0
    analysis_window_seconds: int = 900
    auto_investigate: bool = False  # read-only diagnostics only; never proposes or executes actions
    retention_days: int = 7  # events older than this are purged unless an incident cites them
    purge_interval_seconds: int = 3600
    # An approval is only good for this long: conditions may have changed since it was given.
    approval_ttl_seconds: int = 1800


def get_settings() -> Settings:
    return Settings()
