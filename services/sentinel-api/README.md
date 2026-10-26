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

## Incident analysis (Phase 3)

`POST /api/v1/incidents/analyze?window_seconds=900&as_of=<ISO time>` reads stored request events, detects anomalies, groups them into incidents, and writes hypotheses with an evidence ledger. `GET /api/v1/incidents` and `GET /api/v1/incidents/{id}` read them back.

- **Detection** (`app/analysis/detect.py`): per route, the last 120 s is compared with the earlier baseline. Errors: rate above 10% and 10 points over baseline. Latency: p95 at least 2x baseline (and MAD-based) and 200 ms higher. Needs at least 5 recent and 20 baseline requests, otherwise no incident is raised. All thresholds live in `DetectionConfig`.
- **Hypotheses** (`app/analysis/hypotheses.py`): release regression, payment provider timeout, slow dependency, traffic surge. Each gets evidence that supports, contradicts, or is missing, with an explanation built from the measured numbers and the ids of the stored events behind it.
- **Score** (`score-v1`): `1.0*support + 0.5*temporal + 0.3*dependency - 1.2*contradicting - 0.5*missing`. It is a ranking heuristic, not a probability (`score_is_probability` is always false). Timing and topology only count when something supports the hypothesis.
- **Abstention**: a hypothesis is `leading` only with score >= 1.0 and a lead of >= 0.5 over the next one. Otherwise the incident is `inconclusive` and the top hypothesis is `uncertain`.
- **Known limits**: no deployment feed or database metrics are ingested, so release changes are inferred from version labels and a slow dependency is never "confirmed"; these appear as `missing` evidence. The recommended `next_test_id` is a suggestion only; diagnostic tests are not executed yet. Thresholds and weights have not been tuned on held-out data.
