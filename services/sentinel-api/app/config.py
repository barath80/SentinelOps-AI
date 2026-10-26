from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SENTINEL_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./sentinel.db"
    # Bearer token accepted on ingest. Empty means "reject everything": there is no
    # open default, so a missing secret fails closed.
    ingest_token: str = ""
    # Single-tenant MVP: all ingested events belong to this tenant.
    default_tenant_id: str = "00000000-0000-0000-0000-000000000001"
    max_batch_events: int = 500
    max_body_bytes: int = 1_000_000
    max_future_skew_seconds: int = 300


def get_settings() -> Settings:
    return Settings()
