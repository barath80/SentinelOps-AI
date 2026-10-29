# SentinelOps AI

**Evidence-driven incident investigation and controlled recovery.**

SentinelOps AI is an AI-assisted reliability operations platform for cloud applications. It ingests telemetry and change events, groups related alerts, builds a timeline, ranks competing root-cause hypotheses with supporting and contradicting evidence, identifies missing observations, and proposes a bounded recovery plan. A policy layer gates every action, a recovery contract defines success and rollback conditions, and post-action telemetry decides whether recovery actually worked.

> **Design principle:** never confuse a plausible explanation with a proven cause; never treat an executed action as a verified recovery.

**Status:** working prototype, deployed. The blueprint below is the plan; this section says what exists.

| Live | URL |
| --- | --- |
| ShopSphere demo store (Vercel, Neon Postgres) | https://shopsphere-demo-beta.vercel.app |
| SentinelOps API and dashboard (Render) | https://sentinelops-ai-lukk.onrender.com (dashboard at `/ui/`) |

| Built and tested | Where |
| --- | --- |
| Demo store: 96-product catalogue, search and filters, accounts (email/password, Google when configured), checkout, orders, wishlist, password reset | [apps/shop-web](apps/shop-web) |
| Fault injection: global (`FAULT_SCENARIO`) and scoped per request (`CHAOS_TOKEN`), faults S01-S08 and S11 as real behaviour (connection pool, cache, CPU burn, retrying payment client, clock offset) | `apps/shop-web/src/lib/faults.ts`, `pool.ts`, `cache.ts`, `payment.ts` |
| Telemetry: structured logs and OpenTelemetry-style traces (with per-request CPU time) pushed to SentinelOps | `apps/shop-web/src/lib/log.ts`, `trace.ts` |
| Ingestion: JSON, text, normalized, span and metric adapters; idempotent | [services/sentinel-api](services/sentinel-api) |
| Detection, incident grouping, eight ranked cause hypotheses, evidence ledger, per-symptom attribution | `app/analysis/` |
| Telemetry-quality check (clock running ahead) | `app/analysis/quality.py` |
| Failure-propagation graph and earliest containment point, scored against ground truth | `app/analysis/propagation.py` |
| Eight falsification tests (logs, metrics and traces) and the investigation loop | `app/analysis/diagnostics.py` |
| Policy engine, recovery contracts, four-eyes approval, audit trail, SLO verification | `app/recovery/` |
| Recovery rehearsal (counterfactual replay, gates approval) and rollback of failed actions | `app/recovery/rehearsal.py`, `contracts.py` |
| Operator sign-in with roles (viewer, responder, approver, admin); machine token limited to ingest and analysis | `app/auth.py` |
| Incident-to-prevention compiler with human review | `app/prevention.py` |
| Learned root-cause model: notebook, model card, shadow mode in the API, incident labels | [notebook](services/sentinel-api/notebooks/root_cause_model.ipynb), [model card](services/sentinel-api/models/MODEL_CARD.md) |
| Dashboard with sign-in | `app/ui/` |
| Benchmark against baselines (simulated) | [docs/benchmark-results.md](docs/benchmark-results.md) |
| Labelled-incident campaign and evaluation on the live system; end-to-end run of every new scenario, recovery and rollback on the real application | [docs/real-incidents.md](docs/real-incidents.md) |
| Browser tests: shop checkout journey, dashboard sign-in, roles, four-eyes approval and execution | `apps/shop-web/e2e/`, `apps/shop-web/e2e-dashboard/` |
| CI (tests, lint, typecheck, benchmark smoke run, image build), local stack | [.github/workflows/ci.yml](.github/workflows/ci.yml), [docker-compose.yml](docker-compose.yml) |

**Headline results, with their limits.** On the simulated benchmark (12 scenarios plus 2 probes, 20 seeds each), full SentinelOps names the right cause in 179/180 determinable runs (99%) against 33% for a naive log-based alert correlator, proposes a wrong recovery action in 0/200 fault runs against 42%, names the true origin as the earliest containment point in 157/160 runs, and flags the clock-skew scenario every time with no false warnings in 260 other runs. Rehearsal alone halves wrong actions (20% to 10%) and removes them on the probes. The scenarios were written by the same author as the system, and SentinelOps reads traces that the baselines do not, so these numbers show the mechanisms work, not that they generalize. On the real application run locally, every scenario was diagnosed correctly after investigation (8/8 labelled incidents, containment point right 7/7), all seven recoveries succeeded through the real executor and a rollback was verified to restore the fault. On 12 real labelled incidents from the deployed system the rule engine was right 11 times and the learned shadow model 12 times, with no wrong recovery action from either; 12 incidents give wide intervals (see the report).

**Not built or not yet run:** the LLM-only baseline run (needs an `ANTHROPIC_API_KEY`); the campaign for S02, S04, S06, S07 and S11 against the *deployed* shop and API (it has been run end to end against the real application locally; the deployed run needs the new code deployed); single sign-on and multiple tenants; a sandbox *copy* of production (rehearsal replays recorded telemetry instead); a production executor (out of scope by design). The learned model runs in shadow mode only and never drives a decision.

## Run it

```
# Tests
cd services/sentinel-api && pip install -r requirements.txt && python -m pytest -q
cd apps/shop-web && npm ci && npx tsc --noEmit && npm run lint && npm test
cd apps/shop-web && npx playwright install chromium && npx playwright test        # shop journeys
cd apps/shop-web && npx playwright test -c playwright.dashboard.config.ts            # dashboard (starts the API)

# SentinelOps API + dashboard with its own Postgres (http://localhost:8000/ui/, admin / change-me-local-only)
docker compose up --build

# Or without Docker (PowerShell: $env:NAME="value")
cd services/sentinel-api
SENTINEL_INGEST_TOKEN=<machine token> SENTINEL_SESSION_SECRET=<32+ random chars> \
SENTINEL_BOOTSTRAP_ADMIN=admin:<12+ char password> python -m uvicorn app.asgi:app --port 8000

# The shop locally, pushing to it, with an in-memory order store (no real database is touched)
cd apps/shop-web && npm run build
SHOP_DB=memory CHAOS_TOKEN=<16+ chars> ADMIN_TOKEN=<secret> SENTINEL_INGEST_URL=http://127.0.0.1:8000 \
SENTINEL_INGEST_TOKEN=<machine token> npx next start -p 3000

# Benchmark (simulated, hidden ground truth)
cd services/sentinel-api && python -m benchmark --seeds 20 --out ../../docs/benchmark-results.md

# Labelled campaign against a running shop + API (scoped faults; a responder operator labels)
CHAOS_TOKEN=... SENTINEL_TOKEN=<machine token> SENTINEL_OPERATOR=campaign SENTINEL_OPERATOR_PASSWORD=... \
python -m campaign.run_campaign --shop <shop> --sentinel <api> --scenarios S01 S02 S03 S04 S05 S06 S07 S08 none surge S11 --investigate
python -m campaign.evaluate --sentinel <api>

# End-to-end recovery and rollback through the real shop_admin executor (API started with
# SENTINEL_EXECUTOR=shop_admin; use a shop instance nobody else uses: faults are switched globally)
SHOP_ADMIN_TOKEN=... SENTINEL_TOKEN=... SENTINEL_RESPONDER=alice:... SENTINEL_APPROVER=bob:... \
python -m campaign.e2e_recovery --shop <shop> --sentinel <api> --scenarios S01 S02 S03 S04 S05 S06 S07 --rollback S02
```

## Research question

Does falsification-guided diagnosis plus risk-aware recovery reduce incorrect interventions and failed recoveries compared with simple alert correlation and LLM-only baselines?

## Key features

| Feature | Summary |
| --- | --- |
| Evidence ledger | Every claim links to a retrievable source (metric query, log, trace span, deployment, runbook). The LLM cannot invent IDs or values. |
| Self-challenging root-cause engine | Ranks hypotheses with a transparent, versioned score, then runs read-only tests meant to *disprove* the leader. Reports uncertainty instead of forcing a winner. |
| Diagnostic-test selection | Picks allow-listed read-only checks by expected information gain and cost. |
| Failure-propagation reconstruction | Temporal graph of observed, inferred and unknown edges; earliest-containment analysis. |
| Recovery rehearsal lab | Applies a candidate action in an isolated sandbox before anything else. Results are labelled as sandbox evidence. |
| Blast-radius prediction | Dependency-graph reachability and a conservative risk score (not a probability). |
| Recovery contracts | Machine-readable target, preconditions, guardrails, verification window and rollback, evaluated by code. |
| Incident-to-prevention compiler | Proposes regression tests, alert rules and runbook edits for human review. Nothing is auto-merged. |
| Reliability Challenge Arena | Reproducible benchmark: alert-correlation baseline vs LLM-only vs SentinelOps on identical telemetry and budgets. |

## Reference application: ShopSphere

A small instrumented e-commerce system (web frontend, gateway, catalog, cart, checkout/order, payment simulator, inventory, PostgreSQL, Redis, load generator, fault injector) serves as both realistic workload and controlled lab. No real payments or personal data are involved.

Initial SLI targets (demo defaults, to be calibrated):

- Checkout success rate ≥ 99% over a 5-minute window
- Checkout p95 latency < 500 ms under fixed demo load
- HTTP 5xx rate < 1%
- Zero duplicate orders per idempotency key
- Recovery verification returns **pass / fail / inconclusive**, never inferred from action execution

## Scenario catalogue (initial 12)

S01 bad checkout deployment · S02 DB connection-pool exhaustion · S03 slow query · S04 Redis/cache unavailable · S05 payment simulator timeout · S06 CPU saturation · S07 retry storm · S08 missing telemetry · S09 misleading deployment correlation · S10 two simultaneous faults · S11 clock skew / delayed events · S12 unsafe remediation candidate.

Ground-truth labels live in a separate benchmark schema and are never visible to the diagnosis agent.

## Architecture

A modular monolith control plane plus separately deployed demo services.

```
React + TS dashboard ──► FastAPI API / Auth
                              │
     ┌────────────────────────┼─────────────────────────┐
 Incident & Correlation   Policy / Recovery Contract   Retrieval (runbooks, cases)
     └────────────────────────┼─────────────────────────┘
                   PostgreSQL (incidents, evidence, hypotheses, approvals, outcomes)
                              ▲
        Redis queue + workers ┴ LLM adapter (structured output)
                              ▲
   OpenTelemetry Collector → Prometheus (metrics) + Loki (logs) + traces
                              ▲
                     ShopSphere demo services
```

Main modules: telemetry adapter, normalizer, anomaly detector, incident grouper, hypothesis engine, evidence ledger, falsification planner, impact estimator, recovery rehearsal, policy engine, recovery verifier, prevention compiler, benchmark runner.

Recovery state machine:

```
PENDING → VALIDATED → AWAITING_APPROVAL → SIMULATING → READY_FOR_SANDBOX_ACTION
        → EXECUTING → VERIFYING → SUCCEEDED | FAILED | INCONCLUSIVE | ROLLED_BACK
```

## Tech stack (MVP)

| Layer | Choice |
| --- | --- |
| Frontend | React, TypeScript, Vite, Tailwind CSS |
| Backend | Python 3.12+, FastAPI, Pydantic |
| Database | PostgreSQL (JSONB, full-text search; pgvector only if retrieval evaluation justifies it) |
| Queue | Redis with one of RQ / Arq / Celery |
| Observability | OpenTelemetry, Prometheus, Loki, Grafana |
| AI | Rules and statistics first; provider-neutral LLM adapter with structured JSON output |
| Analytics | NumPy, pandas, SciPy, scikit-learn |
| Sandbox / load / faults | Docker Compose, Locust or k6, Python fault toggles / Toxiproxy |
| CI/CD | GitHub Actions |

Principle: one frontend, one backend, one database, one queue, one metrics system, one log system, one LLM adapter. Add components only when a measurement justifies them.

## AI and safety rules

- Deterministic code owns telemetry, permissions and recovery status. The LLM only synthesizes and explains.
- LLM output is validated with Pydantic; unknown evidence IDs, tools, or free-form commands are rejected.
- Logs, runbooks and external feeds are treated as untrusted (prompt-injection aware).
- The policy engine is default-deny with allow-listed action templates. There is no shell and no arbitrary SQL tool.
- The MVP is read-only against telemetry and mutates only mock or sandbox resources. There are no production mutations.
- Secrets are redacted before model calls. Model, prompt version, evidence IDs and token cost are logged.
- If the LLM is unavailable, the system still ingests data and shows evidence (degraded mode).

## Planned API (v1)

`POST /api/v1/telemetry/events` · `POST|GET /api/v1/incidents` · `GET /api/v1/incidents/{id}` · `.../hypotheses` · `.../evidence` · `POST .../diagnostics` · `POST /api/v1/recovery-contracts` · `.../approve` · `.../simulate` · `.../verification` · `POST /api/v1/benchmark-runs`

## Observability of SentinelOps itself

The platform monitors its own reliability with Prometheus metrics such as `sentinel_events_ingested_total`, `sentinel_events_rejected_total`, `sentinel_queue_depth`, `sentinel_oldest_job_age_seconds`, `sentinel_investigation_duration_seconds`, `sentinel_llm_requests_total`, `sentinel_evidence_validation_failures_total`, `sentinel_recovery_actions_blocked_total`, `sentinel_recovery_verification_total`, `sentinel_sandbox_runs_active` and `sentinel_db_pool_wait_seconds`. High-cardinality identifiers (incident UUIDs, request IDs) go in logs and traces, never in metric labels.

## Novelty and positioning

AI-assisted root-cause analysis, multi-hypothesis investigation, runbook retrieval and guided remediation already exist in products such as Elastic AI SRE, New Relic SRE Agent, Dynatrace Intelligence and Meta's DrP. SentinelOps does not claim these ideas are new. Comparisons are based on public vendor descriptions, not a patent search or market survey.

What it aims to demonstrate, with measurements:

| Contribution | What must be shown |
| --- | --- |
| Evidence ledger with counterevidence | Every claim resolves to source data; counterevidence and missing data are visible and validated |
| Falsification-guided diagnostics | Fewer wrong top-ranked diagnoses under decoy and counterexample scenarios |
| Recovery rehearsal with risk comparison | Reproducible comparison of candidate fixes in an isolated environment |
| Recovery contracts with SLO verification | Pass / fail / inconclusive status; execution is never treated as success |
| Propagation timeline and earliest containment | Ground-truth evaluation of propagation order and earliest preventable point |
| Incident-to-prevention traceability | Verified cause linked to a passing regression test and a reviewed rule |
| Reliability Challenge Arena | Hidden ground truth, safety metrics and reproducible baseline comparison |

## Evaluation

Three systems are compared on identical telemetry and diagnostic budgets: an alert-correlation baseline, an LLM-only baseline, and SentinelOps. Start with 12 scenarios and grow to at least 50 seeded, parameterized runs.

Metrics: top-1/top-3 root-cause accuracy, evidence precision, false-diagnosis rate, abstention quality, diagnostic cost, recovery success, unsafe-action rate, end-to-end time, and cost per incident and per verified recovery. Repeated runs are reported with variation, and failures and inconclusive results are published.

## Deployment and cost

Build and demo locally with Docker Compose first. Deploy only the public pieces later (static frontend, small API container, managed Postgres, short telemetry retention). Set a hard monthly budget and billing alerts before enabling paid resources, cap LLM tokens per incident, and start sandboxes on demand with hard timeouts. No Kubernetes or vector database until measurements require them.

## Non-goals (first release)

Replacing human SREs, unrestricted production shell access, guaranteed root-cause certainty, training a foundation model, and a full Kubernetes platform before the core workflow works.

## MVP scope

| Build first | Add after the core is stable | Avoid initially |
| --- | --- | --- |
| ShopSphere demo and telemetry | Information-gain diagnostic selection | Training a foundation model |
| Incident timeline and evidence ledger | Recovery rehearsal | Unrestricted production auto-remediation |
| Basic hypothesis scoring | Blast-radius scoring | Full Kubernetes without need |
| Missing-evidence reporting | Incident similarity, prevention PR generation | Separate graph database without need |
| Approval-gated mock actions | Richer causal analysis | Kafka before throughput requires it |
| Recovery verification | Multi-tenant production hardening | Too many overlapping agents |
| Twelve fault scenarios | Automated prevention artifacts | Always-on GPU |

## Roadmap (proposed 20 weeks)

| Phase | Weeks | Deliverables | Acceptance criteria |
| --- | --- | --- | --- |
| 0 Foundation | 1 | Repo, ADR, Docker Compose, CI | One-command startup; lint and smoke tests pass |
| 1 Shop demo | 2–3 | Catalogue, cart, checkout, payment simulator, seed data | Simulated order completes; no real payment |
| 2 Telemetry | 4–5 | OpenTelemetry metrics, logs, traces, deployment and fault events | A known request has correlated trace, log and metric refs |
| 3 Incident core | 6–7 | Anomaly detection, grouping, timeline, evidence schema | A fault creates one incident with source-linked evidence |
| 4 AI investigation | 8–9 | Hypothesis ranking, counterevidence, uncertainty, schema validation | Unknown evidence IDs rejected; ambiguous cases can abstain |
| 5 Safety and recovery | 10–11 | Recovery contracts, approvals, mock action, SLO verification | Unsafe actions blocked; pass/fail/inconclusive tests pass |
| 6 Research features | 12–14 | Falsification planner, rehearsal, impact estimate, prevention proposals | 12 scenario types and baseline comparisons |
| 7 Public demo | 15–16 | Deployment, docs, cost guardrails, demo account | External tester reproduces at least 5 scenarios |
| 8 Evaluation and paper | 17–20 | 50+ runs, metrics, ablations, limitations, report | Reproducible results and failure analysis |

A smaller MVP can ship sooner by deferring causal ML, sandbox cloning and automated prevention artifacts.

## Planned repository layout

```
apps/            shop-web, sentinel-dashboard
services/        shop-api, catalog, cart, checkout, payment-simulator, inventory,
                 sentinel-api (FastAPI control plane), sentinel-worker
packages/        telemetry-contracts, api-schemas, shared-test-fixtures
sentinelops/     ingestion, normalization, anomaly_detection, incident_correlation,
                 hypotheses, evidence_ledger, falsification, retrieval,
                 impact_estimation, recovery_contracts, sandbox, verification,
                 prevention_compiler, benchmark, policy
infra/           docker-compose.yml, otel-collector.yaml, prometheus.yml, loki-config.yaml, dashboards/
scenarios/       S01_bad_deployment/, S02_db_pool_exhaustion/, ...
runbooks/  migrations/  tests/{unit,integration,e2e,security,load}  docs/  .github/workflows/
```

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| LLM hallucination | Evidence-ID validation, deterministic scoring, abstention |
| Correlation mistaken for causation | Falsification checks, decoy scenarios, careful confidence language |
| Sandbox differs from production | Record drift and workload similarity; require approval |
| Unsafe action | Default-deny policy, allow-listed templates, no production mutation in MVP |
| Telemetry gaps | Missing-evidence auditor, inconclusive status |
| Cost spike | Budgets, caps, retention limits, auto-cleanup, billing alerts |
| Duplicate queue delivery | Idempotency keys, state machine, unique DB constraints |
| Tenant data leak | Tenant-scoped queries and explicit cross-tenant tests |
| Wrong generated prevention code | CI tests, human review, no auto-merge |
| Novelty overclaim | Document comparison method; report overlap honestly |

## Reviewer demo script

1. Complete an order in the normal storefront, then open the dashboard (healthy baseline, service map).
2. Trigger S01 (bad deployment) from the Chaos Lab; show the timeline.
3. Show at least three hypotheses (deployment and a DB-saturation alternative) and the evidence ledger with counterevidence and missing telemetry.
4. Run a read-only falsification test, then a sandbox rehearsal labelled as simulation.
5. Approve a mock rollback; watch the recovery contract evaluate SLOs and return pass, fail or inconclusive, with the full audit trail.
6. Generate a regression test or alert rule awaiting human review.
7. Repeat with S08 (missing telemetry) or S09 (misleading deployment) to show abstention and counterevidence.

## Acceptance checklist

- [x] Tester can complete the simulated shopping journey (live store; Playwright checkout journey on the in-memory store)
- [x] Key requests are traceable (one trace per request with pool, query, payment and cache spans; the shop is a single service)
- [x] Each fault scenario reliably produces its expected symptoms: S01, S03, S05, S08 on the deployed system; S01-S08 and S11 end to end on the real application locally (deployed run of the new ones pending)
- [x] Hypotheses and evidence IDs resolve to real data; counterevidence and missing data are shown
- [x] LLM failure does not erase incident or telemetry records (no LLM is in the decision path)
- [x] Unknown evidence IDs and non-allow-listed actions are rejected
- [x] Approval identity and decision are audited (signed-in operators; `X-Actor` is ignored)
- [x] Recovery verification uses measured SLIs over the full window
- [x] Sandbox resources are cleaned up: not applicable, rehearsal replays stored telemetry and creates no resources
- [x] Ground truth is never exposed to the diagnosis agent (tested for every scenario)
- [x] Benchmark reports baselines, failures, latency and cost (LLM tokens once the LLM baseline is run)
- [ ] Deployment has HTTPS and secrets management (done); backups and spend alerts are account settings on Neon, Render and Vercel to switch on

## Novelty caveat

The project statement describes an intended contribution, not a verified world-first claim. Before a paper, patent filing or commercial claim, compare the exact workflow with recent papers, open-source projects and vendor documentation, and record the search terms, dates and exclusions.

## References (starting points, not a literature review)

Elastic Observability · New Relic SRE Agent and Autopilot · Dynatrace Root Cause Analysis · Meta Engineering DrP · OpenTelemetry · Prometheus · Grafana Loki · FastAPI · PostgreSQL · Redis · Locust · Grafana k6 · DoWhy · AgentRCA preprint · Incident-Arena (verify exact title, authors and version before citing).

## License

To be decided.
