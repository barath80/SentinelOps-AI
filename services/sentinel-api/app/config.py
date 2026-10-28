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
    # Record the learned model's prediction next to the rule engine's (never used for decisions).
    shadow_model: bool = True
    # An approval is only good for this long: conditions may have changed since it was given.
    approval_ttl_seconds: int = 1800
    # "operators": people log in and their role decides what they may do; the ingest token is a
    # machine credential (ingest, read, analysis). "shared_token": legacy, identity from X-Actor.
    auth_mode: str = "operators"
    @field_validator("auth_mode")
    @classmethod
    def _known_mode(cls, mode: str) -> str:
        if mode not in ("operators", "shared_token"):
            raise ValueError("auth_mode must be 'operators' or 'shared_token'")
        return mode

    # shared_token mode lets anyone holding the token claim any identity, so it only starts with
    # this explicit development flag, and never on a hosted service (Render sets RENDER).
    allow_insecure_shared_token: bool = False
    # Signs session tokens. Empty means nobody can log in (fails closed). Use 32+ random bytes.
    session_secret: str = ""
    session_ttl_seconds: int = 8 * 3600
    # "username:password" for the first admin; used only while no operator exists.
    bootstrap_admin: str = ""


def get_settings() -> Settings:
    return Settings()
