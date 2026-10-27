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
- **Known limits**: no deployment feed or database metrics are ingested, so release changes are inferred from version labels and a slow dependency is never "confirmed"; these appear as `missing` evidence. The recommended `next_test_id` is run by the diagnostic tests described below. Thresholds and weights have not been tuned on held-out data.

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
- **Not built yet**: recovery rehearsal in a sandbox copy, rollback of a failed action (`rollback_template` is unset), real authentication of actors, and a production executor. Production mutation is out of scope. (Approvals do expire; see Phase 7.)

## Dashboard (Phase 6)

Open `/ui/` on the running API. Enter the bearer token and your name (the name is sent as `X-Actor` and recorded in the audit trail), press Connect, then "Analyze now". It lists incidents, ranked hypotheses with their evidence ledger and score history, per-symptom attribution, diagnostic runs, recovery contracts with approve / execute / verify actions, and prevention proposals with review buttons.

It is plain HTML and JavaScript served by the API (no build step, same origin). Telemetry text is untrusted, so the page only ever sets `textContent`; a test fails if `innerHTML`-style APIs appear, and the CSP forbids inline script and outside hosts. The token is kept in `sessionStorage` (cleared when the tab closes).

## Benchmark

`python -m benchmark --seeds 20 --out ../../docs/benchmark-results.md` runs seeded scenarios against a naive alert correlator, an LLM-only baseline (only if `ANTHROPIC_API_KEY` is set), and SentinelOps with and without the falsification loop, on identical telemetry with hidden ground truth. Results and caveats: [docs/benchmark-results.md](../../docs/benchmark-results.md).

## Deployment

See [docs/deploy-api.md](../../docs/deploy-api.md). Use a Postgres `SENTINEL_DATABASE_URL`; run `python -m app.migrate` once if you set `SENTINEL_AUTO_CREATE_SCHEMA=false`.

## Multi-symptom attribution, upkeep and prevention (Phase 7)

**Attribution by symptom** (`app/analysis/attribution.py`): besides the incident-level ranking, each anomaly (route + kind) is ranked on its own and reported in `summary.attribution` as `single_cause`, `multi_cause`, `partial` (some symptoms explained, others listed in `unexplained_symptoms`), or `unexplained`. A release-label change counts for less (0.4 instead of 0.8) when the symptom is slowness without errors, because release defects usually show up as errors. Attribution is computed at analysis time and is not re-run after diagnostics.

**Upkeep** (`app/maintenance.py`), all off or conservative by default:
- `SENTINEL_ANALYZE_INTERVAL_SECONDS` (default 0 = off) runs analysis periodically; `SENTINEL_AUTO_INVESTIGATE=true` also runs the read-only diagnostics once per open incident. The scheduler never proposes, approves or executes an action. A failed pass is logged and the loop continues.
- Retention: `SENTINEL_RETENTION_DAYS` (default 7) and `POST /api/v1/maintenance/purge?days=N` delete old events, **except** events cited by stored evidence or diagnostic runs, so ledger links keep resolving.
- Approvals expire after `SENTINEL_APPROVAL_TTL_SECONDS` (default 1800); executing a stale approval returns `approval_expired`.

**Prevention compiler** (`app/prevention.py`): `POST /api/v1/incidents/{id}/prevention` (needs `X-Actor`) works only once a cause is confirmed, meaning the incident is resolved by a contract whose verification passed and whose action was the recommended fix for the leading cause. It stores a regression test, an alert rule, a runbook amendment, and one follow-up per missing-evidence item. Each links to the ledger evidence and source events, passes static checks (parses, allow-listed imports, no dynamic code or file access, no secrets, targets `SHOP_URL` rather than a hard-coded host), starts as `proposed`, and changes only via `POST /api/v1/prevention-artifacts/{id}/review`. Nothing is executed, deployed or merged by the system. A generated regression test was run against the real shop: it passes when healthy and fails (500) with the bad release active.

## Learned root-cause model (Phase 8)

[`notebooks/root_cause_model.ipynb`](notebooks/root_cause_model.ipynb) trains a classifier that predicts an incident's cause from detector features, with calibrated probabilities and abstention. Data comes from a parametric simulator (`training/generator.py`); features are computed from telemetry by the production detector (`training/features.py`). Logistic regression, random forest and gradient boosting are tuned with stratified 5-fold CV; the winner is calibrated, given an abstention threshold for 99% precision, and tested on an in-distribution and a shifted held-out set against the rule engine. Results, limits and reproduction steps: [`models/MODEL_CARD.md`](models/MODEL_CARD.md). The model is a research artifact trained on simulated data and is not used by the API.

## Traces, metrics, shadow model and labels (Phase 9)

- **Traces and metrics.** Two more ingest adapters: `otel_span` (one span in OpenTelemetry's JSON shape: `traceId`, `spanId`, `parentSpanId`, `name`, `serviceName`, `startTimeUnixNano`, `endTimeUnixNano`, `status`, flat `attributes`) and `metric` (`name`, `value`, `timestamp`, `serviceName`, `labels`). The demo shop now emits a root span per API request plus child spans for each database query and the payment call, and puts the `trace_id` on its log lines.
- **Trace-aware diagnostics.** `inspect_db_pool_wait_and_query_duration` uses database metrics when they exist and otherwise request traces: if database spans hold at least half of the slow requests' time it supports `slow_dependency`, at most 20% contradicts it. `inspect_payment_provider_status_and_spans` matches failing requests to a payment timeout through either a log line or a failed/slow `payment.*` span. On the real shop under fault S03 this turned the previous "untestable" result into "database spans account for 100% of the slow requests' time (14 traces)".
- **Shadow model.** Every incident records a prediction from the compact learned model (`app/models/root_cause_serving_v1.json`, pure-Python inference, no pickle) next to the rule engine's answer, plus the feature vector it used. It is recorded only; it never changes rankings, recommendations or actions. Turn it off with `SENTINEL_SHADOW_MODEL=false`. `GET /api/v1/shadow/report` shows agreement with the rules and, once incidents are labelled, the accuracy of both.
- **Labels.** `POST /api/v1/incidents/{id}/label {"label", "note"}` (with `X-Actor`) records a person's judgement of the true cause; `GET /api/v1/training/labelled` exports labelled incidents with their features, the evaluation set for the next model.
