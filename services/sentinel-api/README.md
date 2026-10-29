# sentinel-api

SentinelOps control-plane API (FastAPI): telemetry ingestion, incident analysis, falsification-guided diagnosis, recovery contracts with rehearsal, verification and rollback, prevention proposals, and the operator dashboard.

## Run

    pip install -r requirements.txt
    set SENTINEL_INGEST_TOKEN=choose-a-secret      # PowerShell: $env:SENTINEL_INGEST_TOKEN="..."
    set SENTINEL_SESSION_SECRET=<32+ random characters>
    set SENTINEL_BOOTSTRAP_ADMIN=admin:<12+ character password>
    python -m uvicorn app.asgi:app --port 8100
    python -m pytest -q

Settings come from `SENTINEL_*` environment variables (see `app/config.py` and `.env.example`). With no `SENTINEL_INGEST_TOKEN` no machine request is accepted, and with no `SENTINEL_SESSION_SECRET` nobody can sign in. Or run the whole stack with its own Postgres: `docker compose up --build` at the repository root. `SENTINEL_DATABASE_URL` defaults to a local SQLite file; use a Postgres URL (for example Neon) for anything shared.

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
- **Hypotheses** (`app/analysis/hypotheses.py`): release regression, payment provider timeout, slow dependency, traffic surge, plus four causes request logs cannot show (connection-pool exhaustion, cache unavailable, CPU saturation, retry storm; see Phase 11). Each gets evidence that supports, contradicts, or is missing, with an explanation built from the measured numbers and the ids of the stored events behind it.
- **Score** (`score-v1`): `1.0*support + 0.5*temporal + 0.3*dependency - 1.2*contradicting - 0.5*missing`. It is a ranking heuristic, not a probability (`score_is_probability` is always false). Timing and topology only count when something supports the hypothesis.
- **Abstention**: a hypothesis is `leading` only with score >= 1.0 and a lead of >= 0.5 over the next one. Otherwise the incident is `inconclusive` and the top hypothesis is `uncertain`.
- **Known limits**: no deployment feed or database metrics are ingested, so release changes are inferred from version labels and a slow dependency is never "confirmed"; these appear as `missing` evidence. The recommended `next_test_id` is run by the diagnostic tests described below. Thresholds and weights have not been tuned on held-out data.

## Diagnostic tests and the investigation loop (Phase 4)

Eight allow-listed, read-only tests (`app/analysis/diagnostics.py`) try to *disprove* a hypothesis from stored events: `compare_error_rate_before_after_release`, `inspect_payment_provider_status_and_spans`, `inspect_db_pool_wait_and_query_duration`, `compare_request_rate_to_baseline`, `inspect_db_pool_acquire_wait`, `inspect_cache_spans`, `inspect_cpu_time`, `inspect_retry_amplification`. Unknown test ids are rejected with 400; nothing can run a shell, arbitrary SQL, or a network call.

- `POST /api/v1/incidents/{id}/diagnostics {"test_id": ...}` runs one test (re-running replaces its previous run).
- `POST /api/v1/incidents/{id}/investigate {"budget": 4}` (1 to 8) tests the leader first, then live alternatives. It stops early only when the leader passes a **decisive** test (support strength >= 0.8); a merely suggestive result keeps testing the alternatives. Stop reasons: `leader_survived_falsification` (decisive), `leader_stands_alternatives_ruled_out` (suggestive, but every live alternative was tested and none overtook it), `leader_untestable_missing_data`, `no_runnable_tests`, `budget_exhausted`. This rule came from a live campaign incident where a release deployed exactly as a slow-query fault began: the release test only restated the coincidence, stopped the loop, and the wrong cause won; testing the alternative (traces) gets it right.
- A result becomes ledger evidence (`created_by: diagnostic:<test>`). A direct contradiction (strength >= 0.8) marks the hypothesis `falsified`: it can no longer lead, and the incident becomes `inconclusive` rather than promoting an unsupported alternative. Earlier scores are kept in `score_history`, and diagnostics survive re-analysis.
- If a test lacks data (for example no database metrics are ingested) it returns `no_data` and adds no evidence. The leader is reported as untestable, never as confirmed.

## Recovery contracts and SLO verification (Phase 5)

Flow: `POST /api/v1/recovery-contracts` (propose) -> `/{id}/approve` -> `/{id}/execute` -> `/{id}/verify`; `GET /{id}` returns the contract, audit trail, approvals, action run and verifications. `GET /api/v1/recovery-actions` lists the allow-list. Acting needs a signed-in operator: proposing, rehearsing, executing, verifying and rolling back need the `responder` role, approving needs `approver` (see Phase 12). The machine token can read contracts but never act.

- **Policy** (`app/recovery/policy.py`, `policy-v1`): default deny. Unknown actions, environments outside the action's allow-list (production is never allowed), and disruptive actions that reach critical dependents are blocked. A blocked contract is stored with its reasons and can never proceed (scenario S12: `restart_shared_database`). Blast radius is deterministic reachability over a static topology, labelled low/medium/high, not a probability.
- **State machine**: `VALIDATED -> AWAITING_APPROVAL -> READY_FOR_ACTION -> EXECUTING -> VERIFYING -> SUCCEEDED | FAILED | INCONCLUSIVE` (plus `REJECTED`, `BLOCKED`). Every change is an atomic compare-and-set plus an append-only audit row (actor, time, policy version).
- **Four eyes**: the proposer cannot approve their own contract. An action runs at most once per contract.
- **Verification** is computed only from telemetry inside the window that starts when the action finishes. Before the window closes the answer is `pending`. A success condition that is measurably missed, or a breached guardrail, is `fail`. Too few samples (error rate needs 5, p95 needs 20) or a telemetry gap is `inconclusive`, never `pass`. A successful action with failing telemetry is `FAILED`.
- **SLO targets**: error rate <= 1%; p95 <= max(500 ms, 1.5 x the route's pre-incident p95). The basis is stored in the contract (`slo_basis`). A fixed 500 ms was unreachable on the demo setup (checkout writes to a remote database, healthy p95 about 550 ms), so the target is anchored to the measured baseline. A baseline with outliers (for example one cold start in a small sample) gives a looser target, so the basis is shown and should be reviewed at approval.
- **Executors**: `mock` (default, records the call only) and `shop_admin` (sets the demo shop's fault scenario to `none` via its admin endpoint). Set `SENTINEL_EXECUTOR=shop_admin`, `SENTINEL_SHOP_ADMIN_URL`, `SENTINEL_SHOP_ADMIN_TOKEN`.
- **Not built yet**: real authentication of actors and a production executor. Production mutation is out of scope. (Approvals do expire; see Phase 7. Rehearsal and rollback: see below.)

## Recovery rehearsal and rollback (Phase 10)

**Rehearsal** (`app/recovery/rehearsal.py`, `rehearsal-v1`). Every new contract is rehearsed when it is proposed, and `POST /api/v1/recovery-contracts/{id}/rehearse` re-runs it before the action executes. A rehearsal replays the incident window's recorded telemetry with the action's modelled effect and scores the result with the same SLO evaluator that verification uses:

| Action | Modelled effect | Inconclusive when |
| --- | --- | --- |
| `rollback_release` | Affected traffic behaves like the requests still on the previous release in the same window | No request in the window ran on the previous release |
| `restore_payment_simulator` | Failing requests linked to a payment timeout (log line or payment span) succeed; provider wait time is removed | No failing request is linked to a timeout |
| `apply_query_fix` | Database-span time above the baseline is removed from traced requests | No affected request has database spans |

The outcome is `pass`, `fail` or `inconclusive`, and it is labelled as simulation evidence: no system is touched, and a pass is not a recovery. Rehearsal accepts fewer samples than verification (error rate 5, p95 10) because it only has the incident window. Its main use is the other direction: **if the rehearsal fails, approval is refused** (`rehearsal_failed`) unless the approver sends `acknowledge_rehearsal_failure: true`, and that choice is stored on the audit row. Example: the old release fails as well as the new one, so the replay shows a rollback cannot meet the contract.

**Rollback.** Before an action runs, the executor captures the state it will change (`capture`). If that fails, the action is not attempted and the contract is `FAILED`. After a `FAILED` or `INCONCLUSIVE` verdict, `POST /{id}/rollback {"reason"}` runs the contract's `rollback_template` (for example `revert_rollback_release`), which restores the captured state: `FAILED | INCONCLUSIVE -> ROLLING_BACK -> ROLLED_BACK | ROLLBACK_FAILED`. Details:

- The rollback is part of the approved plan, so it needs no second approval, but it is policy-checked and audited. Revert templates cannot be proposed as contracts on their own.
- It runs at most once per contract (unique `rollback_runs.contract_id`). A succeeded contract cannot be rolled back.
- A breached guardrail sets `rollback_recommended`, because then the action itself may be doing harm. A merely unmet success condition allows a rollback but does not recommend one.
- The contract's outcome is unchanged and the incident stays open: undoing a change is not a recovery. A new contract can then be proposed.
- **Rollback is verified**: after the revert the executor reads the state back, and the rollback only counts as `ROLLED_BACK` when it equals the captured pre-action state (`rollback_run.output.verification`). A revert that reports success but leaves another state is `ROLLBACK_FAILED`.
- With the `shop_admin` executor, capture reads the active fault scenario and revert sets it back. That can re-activate the original fault, which is what restoring the previous state means.

## Dashboard (Phase 6)

Open `/ui/` on the running API and sign in (in legacy `shared_token` mode: enter the token and your name), then press "Analyze now". It lists incidents, ranked hypotheses with their evidence ledger and score history, per-symptom attribution, the failure-propagation chain and containment point, diagnostic runs, recovery contracts with rehearse / approve / execute / verify / roll back actions, prevention proposals with review buttons, and a banner when telemetry quality is suspect.

It is plain HTML and JavaScript served by the API (no build step, same origin). Telemetry text is untrusted, so the page only ever sets `textContent`; a test fails if `innerHTML`-style APIs appear, and the CSP forbids inline script and outside hosts. The token is kept in `sessionStorage` (cleared when the tab closes).

## Benchmark

`python -m benchmark --seeds 20 --out ../../docs/benchmark-results.md` runs seeded scenarios against a naive alert correlator, an LLM-only baseline (only if `ANTHROPIC_API_KEY` is set), and SentinelOps with and without the falsification loop and the rehearsal gate (`sentinel`, `sentinel_falsify`, `sentinel_rehearse`, `sentinel_full`), on identical telemetry with hidden ground truth. Scenarios S00-S11 plus probes P1 and P2 carry traces shaped like the real shop's; the baselines read only the logs. Results and caveats: [docs/benchmark-results.md](../../docs/benchmark-results.md).

## Deployment

See [docs/deploy-api.md](../../docs/deploy-api.md). Use a Postgres `SENTINEL_DATABASE_URL`; run `python -m app.migrate` once if you set `SENTINEL_AUTO_CREATE_SCHEMA=false`.

## Multi-symptom attribution, upkeep and prevention (Phase 7)

**Attribution by symptom** (`app/analysis/attribution.py`): besides the incident-level ranking, each anomaly (route + kind) is ranked on its own and reported in `summary.attribution` as `single_cause`, `multi_cause`, `partial` (some symptoms explained, others listed in `unexplained_symptoms`), or `unexplained`. A release-label change counts for less (0.4 instead of 0.8) when the symptom is slowness without errors, because release defects usually show up as errors. Attribution is computed at analysis time and is not re-run after diagnostics.

**Upkeep** (`app/maintenance.py`), all off or conservative by default:
- `SENTINEL_ANALYZE_INTERVAL_SECONDS` (default 0 = off) runs analysis periodically; `SENTINEL_AUTO_INVESTIGATE=true` also runs the read-only diagnostics once per open incident. The scheduler never proposes, approves or executes an action. A failed pass is logged and the loop continues.
- Retention: `SENTINEL_RETENTION_DAYS` (default 7) and `POST /api/v1/maintenance/purge?days=N` delete old events, **except** events cited by stored evidence or diagnostic runs, so ledger links keep resolving.
- Approvals expire after `SENTINEL_APPROVAL_TTL_SECONDS` (default 1800); executing a stale approval returns `approval_expired`.

**Prevention compiler** (`app/prevention.py`): `POST /api/v1/incidents/{id}/prevention` (responder) works only once a cause is confirmed, meaning the incident is resolved by a contract whose verification passed and whose action was the recommended fix for the leading cause. It stores a regression test, an alert rule, a runbook amendment, and one follow-up per missing-evidence item. Each links to the ledger evidence and source events, passes static checks (parses, allow-listed imports, no dynamic code or file access, no secrets, targets `SHOP_URL` rather than a hard-coded host), starts as `proposed`, and changes only via `POST /api/v1/prevention-artifacts/{id}/review`. Nothing is executed, deployed or merged by the system. A generated regression test was run against the real shop: it passes when healthy and fails (500) with the bad release active.

## Learned root-cause model (Phase 8)

[`notebooks/root_cause_model.ipynb`](notebooks/root_cause_model.ipynb) trains a classifier that predicts an incident's cause from detector features, with calibrated probabilities and abstention. Data comes from a parametric simulator (`training/generator.py`); features are computed from telemetry by the production detector (`training/features.py`). Logistic regression, random forest and gradient boosting are tuned with stratified 5-fold CV; the winner is calibrated, given an abstention threshold for 99% precision, and tested on an in-distribution and a shifted held-out set against the rule engine. Results, limits and reproduction steps: [`models/MODEL_CARD.md`](models/MODEL_CARD.md). The model is a research artifact trained on simulated data; a compact version runs in the API in shadow mode only (Phase 9).

## Traces, metrics, shadow model and labels (Phase 9)

- **Traces and metrics.** Two more ingest adapters: `otel_span` (one span in OpenTelemetry's JSON shape: `traceId`, `spanId`, `parentSpanId`, `name`, `serviceName`, `startTimeUnixNano`, `endTimeUnixNano`, `status`, flat `attributes`) and `metric` (`name`, `value`, `timestamp`, `serviceName`, `labels`). The demo shop now emits a root span per API request plus child spans for each database query and the payment call, and puts the `trace_id` on its log lines.
- **Trace-aware diagnostics.** `inspect_db_pool_wait_and_query_duration` uses database metrics when they exist and otherwise request traces: if database spans hold at least half of the slow requests' time it supports `slow_dependency`, at most 20% contradicts it. `inspect_payment_provider_status_and_spans` matches failing requests to a payment timeout through either a log line or a failed/slow `payment.*` span. On the real shop under fault S03 this turned the previous "untestable" result into "database spans account for 100% of the slow requests' time (14 traces)".
- **Shadow model.** Every incident records a prediction from the compact learned model (`app/models/root_cause_serving_v2.json`, pure-Python inference, no pickle) next to the rule engine's answer, plus the feature vector it used. It is recorded only; it never changes rankings, recommendations or actions. Turn it off with `SENTINEL_SHADOW_MODEL=false`. `GET /api/v1/shadow/report` shows agreement with the rules and, once incidents are labelled, the accuracy of both.
- **Labels.** `POST /api/v1/incidents/{id}/label {"label", "note"}` (responder) records a person's judgement of the true cause; `GET /api/v1/training/labelled` exports labelled incidents with their features, the evaluation set for the next model.

## New causes, telemetry quality and failure propagation (Phase 11)

The demo shop now produces four more faults as real behaviour, each visible only in traces (request logs alone cannot tell them apart from a slow query):

| Scenario | What the shop does | Cause | Diagnostic | Recommended action |
| --- | --- | --- | --- | --- |
| S02 | Connections leak; every query waits out the 1.3 s acquire timeout in a `db.pool.acquire` span | `db_pool_exhaustion` | `inspect_db_pool_acquire_wait`: share of slow requests' time spent waiting for a connection | `recycle_db_pool` |
| S04 | The catalogue cache times out (250 ms) on every get and set; requests fall back to the origin | `cache_unavailable` | `inspect_cache_spans`: share of slow requests with a failed or hung `cache.*` call | `restore_cache` |
| S06 | Every request burns 700 ms of CPU; the shop records real `cpu_ms` (from `process.cpuUsage()`) on each root span, only when no other request overlapped it (the reading is process-wide; otherwise `cpu_ms_skipped: concurrent`) | `resource_saturation` | `inspect_cpu_time`: share of slow requests' time spent on-CPU | `scale_out` |
| S07 | The provider fails 75% of calls after 400 ms; the client retries immediately, up to 5 attempts (one span and one `payment_retry` line each) | `retry_storm` | `inspect_retry_amplification`: provider calls per failing checkout | `enable_retry_backoff` |

- The new hypotheses start with only `missing` evidence, so they never lead from logs alone; the investigation loop reaches them once the obvious candidate is falsified. The slow-query test now counts only `db.query` time (not pool waits), and the payment test needs a timeout signature (a provider call of 2 s or more), so a fast-failing provider that is retried is not called a timeout. Slow-but-succeeding requests with no timeout logged count against the timeout hypothesis.
- Every new action has a revert and a rehearsal model, except `enable_retry_backoff`: fewer retries change both latency and failures in ways recorded telemetry cannot show, so its rehearsal is always inconclusive. A rehearsal now distinguishes "not measured" (inconclusive) from "measured and the action would remove nothing" (the unchanged replay is scored, so it fails): for example a query fix during pool exhaustion.
- **Telemetry quality (S11).** `GET /api/v1/telemetry/quality` and every incident's `summary.telemetry_quality` report a clock running ahead: events stamped more than 30 s after they arrived. Such events are kept (rejecting them would hide the problem) but they fall outside detection. Old timestamps are not flagged, because they cannot be told apart from backfill. In the shop, S11 runs the telemetry clock 4 minutes ahead.
- **Failure propagation** (`app/analysis/propagation.py`, `propagation-v1`, in `summary.propagation`). From recorded spans: nodes for the routes, the pool, the database, the payment provider, the cache and the service's compute; edges `observed`, `not_reached` (called in the baseline, no longer called), `inferred` (declared in the static topology but never seen in a span: health unknown, never blamed) or `no_traces`, each with its `evidence`; anomalous nodes ordered by onset; and the **earliest containment** point with how to contain it there (for example "bound provider calls" at the payment provider). When every traced dependency behaves normally the containment point is `service-code`. It is temporal evidence, not proof of causation. The benchmark scores it against the true origin.
- **Learned model v2** adds 8 trace features (time waiting for a connection, in queries, in failed cache calls and on-CPU; provider calls per request; hung payment calls; retry logs) and the four new causes; its simulator now emits partial, sometimes absent, traces. v1 (log features only) could not tell these causes from a slow query and got 4/8 of the real-application incidents; v2 gets 8/8 (`python -m campaign.evaluate --recompute-from <database url>` rebuilds stored incidents with the current features). Still shadow only.
- **Diagnostics use the incident's own analysis window** (`summary.analysis_window_seconds`). They used a fixed 900 s lookback, which on the real application pulled an earlier run's fault into the baseline and made the incident impossible to rebuild.

## Operator authentication (Phase 12)

`app/auth.py`. The default `SENTINEL_AUTH_MODE=operators`:

- People sign in with `POST /api/v1/auth/login {"username", "password"}` and get a signed session token (HMAC-SHA256 with `SENTINEL_SESSION_SECRET`, 8 hours). Passwords are scrypt hashes; 12 characters minimum. Five failed sign-ins lock that username *from that client address* for 15 minutes (per instance), so a stranger cannot lock a real operator out; the container runs uvicorn with `--proxy-headers` so the address is the real client's behind Render's proxy.
- Every request re-reads the operator, so the role used is the current one and disabling an operator, changing a password (`POST /api/v1/auth/password`) or signing out (`POST /api/v1/auth/logout`, all devices) revokes their sessions at once.
- Roles: `viewer` reads; `responder` also analyses, investigates, labels, proposes, rehearses, executes, verifies, rolls back and generates prevention proposals; `approver` also approves contracts and reviews prevention artifacts; `admin` also manages operators (`GET/POST /api/v1/operators`, `PATCH /api/v1/operators/{username}` for role or `disabled`) and runs the retention purge. Admins cannot demote or disable themselves.
- The audit trail records the signed-in username. An `X-Actor` header is ignored, so nobody can approve their own contract by claiming another name.
- The `SENTINEL_INGEST_TOKEN` is a **machine** credential: ingest, reads and the read-only analysis (analyze, diagnostics, investigate). It gets 403 `operator_login_required` on anything a person must answer for.
- `SENTINEL_BOOTSTRAP_ADMIN=username:password` creates the first admin while no operator exists. `GET /api/v1/auth/mode` tells the dashboard which sign-in form to show.
- `SENTINEL_AUTH_MODE=shared_token` keeps the old behaviour (the token grants everything, identity from `X-Actor`). It refuses to start unless `SENTINEL_ALLOW_INSECURE_SHARED_TOKEN=true`, and never starts on Render or Vercel. Development and tests only.
