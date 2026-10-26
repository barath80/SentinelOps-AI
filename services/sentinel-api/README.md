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

## Diagnostic tests and the investigation loop (Phase 4)

Four allow-listed, read-only tests (`app/analysis/diagnostics.py`) try to *disprove* a hypothesis from stored events: `compare_error_rate_before_after_release`, `inspect_payment_provider_status_and_spans`, `inspect_db_pool_wait_and_query_duration`, `compare_request_rate_to_baseline`. Unknown test ids are rejected with 400; nothing can run a shell, arbitrary SQL, or a network call.

- `POST /api/v1/incidents/{id}/diagnostics {"test_id": ...}` runs one test (re-running replaces its previous run).
- `POST /api/v1/incidents/{id}/investigate {"budget": 3}` tests the leader first, then live alternatives. It stops with one of `leader_survived_falsification`, `leader_untestable_missing_data`, `no_runnable_tests`, or `budget_exhausted`.
- A result becomes ledger evidence (`created_by: diagnostic:<test>`). A direct contradiction (strength >= 0.8) marks the hypothesis `falsified`: it can no longer lead, and the incident becomes `inconclusive` rather than promoting an unsupported alternative. Earlier scores are kept in `score_history`, and diagnostics survive re-analysis.
- If a test lacks data (for example no database metrics are ingested) it returns `no_data` and adds no evidence. The leader is reported as untestable, never as confirmed.

## Recovery contracts and SLO verification (Phase 5)

Flow: `POST /api/v1/recovery-contracts` (propose) -> `/{id}/approve` -> `/{id}/execute` -> `/{id}/verify`; `GET /{id}` returns the contract, audit trail, approvals, action run and verifications. `GET /api/v1/recovery-actions` lists the allow-list. All calls need the bearer token and an `X-Actor` header (identity is asserted by the caller until a real OIDC provider is added).

- **Policy** (`app/recovery/policy.py`, `policy-v1`): default deny. Unknown actions, environments outside the action's allow-list (production is never allowed), and disruptive actions that reach critical dependents are blocked. A blocked contract is stored with its reasons and can never proceed (scenario S12: `restart_shared_database`). Blast radius is deterministic reachability over a static topology, labelled low/medium/high, not a probability.
- **State machine**: `VALIDATED -> AWAITING_APPROVAL -> READY_FOR_ACTION -> EXECUTING -> VERIFYING -> SUCCEEDED | FAILED | INCONCLUSIVE` (plus `REJECTED`, `BLOCKED`). Every change is an atomic compare-and-set plus an append-only audit row (actor, time, policy version).
- **Four eyes**: the proposer cannot approve their own contract. An action runs at most once per contract.
- **Verification** is computed only from telemetry inside the window that starts when the action finishes. Before the window closes the answer is `pending`. A success condition that is measurably missed, or a breached guardrail, is `fail`. Too few samples (error rate needs 5, p95 needs 20) or a telemetry gap is `inconclusive`, never `pass`. A successful action with failing telemetry is `FAILED`.
- **SLO targets**: error rate <= 1%; p95 <= max(500 ms, 1.5 x the route's pre-incident p95). The basis is stored in the contract (`slo_basis`). A fixed 500 ms was unreachable on the demo setup (checkout writes to a remote database, healthy p95 about 550 ms), so the target is anchored to the measured baseline. A baseline with outliers (for example one cold start in a small sample) gives a looser target, so the basis is shown and should be reviewed at approval.
- **Executors**: `mock` (default, records the call only) and `shop_admin` (sets the demo shop's fault scenario to `none` via its admin endpoint). Set `SENTINEL_EXECUTOR=shop_admin`, `SENTINEL_SHOP_ADMIN_URL`, `SENTINEL_SHOP_ADMIN_TOKEN`.
- **Not built yet**: recovery rehearsal in a sandbox copy, rollback of a failed action (`rollback_template` is unset), approval expiry, real authentication of actors, and a production executor. Production mutation is out of scope.
