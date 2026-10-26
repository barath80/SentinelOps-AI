# sentinel-api

SentinelOps control-plane API (FastAPI). Currently: telemetry ingestion only.

## Run

    pip install -r requirements.txt
    set SENTINEL_INGEST_TOKEN=choose-a-secret      # PowerShell: $env:SENTINEL_INGEST_TOKEN="..."
    python -m uvicorn app.asgi:app --port 8100
    python -m pytest -q

Settings come from `SENTINEL_*` environment variables (see `app/config.py`). With no `SENTINEL_INGEST_TOKEN` every request is rejected. `SENTINEL_DATABASE_URL` defaults to a local SQLite file; use a Postgres URL (for example Neon) for anything shared.

## Ingest

`POST /api/v1/telemetry/events?adapter=<name>` with `Authorization: Bearer <token>` and body `{"events": [ ... ]}`.

| Adapter | Input |
| --- | --- |
| `normalized` | Already in the `NormalizedEvent` shape (`app/schemas.py`) |
| `shop_json` | The structured log line emitted by `apps/shop-web` |
| `text` | `{"line": "...", "service_name": "..."}`; extracts time, level and a log template |

To support another source, add a function to `app/adapters.py` and register it in `ADAPTERS`.

Behavior: the server sets `tenant_id` and `ingest_time` (clients cannot); events are idempotent by `(tenant_id, event_id)`; bad records are reported per index without failing the batch; events more than 5 minutes in the future and timestamps without a timezone are rejected; batch and body sizes are capped.

`GET /api/v1/telemetry/events?service=&limit=` lists recent events.
