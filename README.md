# SentinelOps AI

**Evidence-driven incident investigation and controlled recovery.**

SentinelOps AI is an AI-assisted reliability operations platform for cloud applications. It ingests telemetry and change events, groups related alerts, builds a timeline, ranks competing root-cause hypotheses with supporting and contradicting evidence, identifies missing observations, and proposes a bounded recovery plan. A policy layer gates every action, a recovery contract defines success and rollback conditions, and post-action telemetry decides whether recovery actually worked.

> **Design principle:** never confuse a plausible explanation with a proven cause; never treat an executed action as a verified recovery.

**Status:** working prototype, not yet deployed. The blueprint below is the plan; this section says what exists. The demo shop is live at https://shopsphere-demo-beta.vercel.app (orders in Neon Postgres). The SentinelOps API and dashboard run locally and are prepared for deployment ([docs/deploy-api.md](docs/deploy-api.md)).

| Built and tested | Where |
| --- | --- |
| ShopSphere demo shop with fault injection (S01, S03, S05) | [apps/shop-web](apps/shop-web) |
| Telemetry ingestion (JSON, text and normalized adapters), idempotent | [services/sentinel-api](services/sentinel-api) |
| Anomaly detection, incident grouping, ranked hypotheses, evidence ledger, per-symptom attribution | `app/analysis/` |
| Falsification tests and investigation loop (explicit stop reasons, `falsified` state) | `app/analysis/diagnostics.py` |
| Policy engine, recovery contracts, four-eyes approval, audit trail, SLO verification (pass / fail / inconclusive) | `app/recovery/` |
| Incident-to-prevention compiler (regression test, alert rule, runbook, monitoring gaps) with human review | `app/prevention.py` |
| Dashboard at `/ui/` | `app/ui/` |
| Benchmark against baselines with hidden ground truth | [docs/benchmark-results.md](docs/benchmark-results.md) |

**Not built:** recovery rehearsal in a sandbox copy, failure-propagation graph, rollback of failed actions, real authentication, live LLM baseline run (needs an API key), and scenarios S02, S04, S06, S07, S11. The benchmark scenarios were written by the same author as the system, so its results show the pipeline works, not that it generalizes. See each document's limits section before relying on a number.

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

- [ ] Tester can complete the simulated shopping journey
- [ ] Key requests are traceable across services
- [ ] Each fault scenario reliably produces its expected symptoms
- [ ] Hypotheses and evidence IDs resolve to real data; counterevidence and missing data are shown
- [ ] LLM failure does not erase incident or telemetry records
- [ ] Unknown evidence IDs and non-allow-listed actions are rejected
- [ ] Approval identity and decision are audited
- [ ] Recovery verification uses measured SLIs over the full window
- [ ] Sandbox resources are cleaned up on success, failure and timeout
- [ ] Ground truth is never exposed to the diagnosis agent
- [ ] Benchmark reports baselines, failures, latency and cost
- [ ] Deployment has HTTPS, secrets management, backups and spend alerts

## Novelty caveat

The project statement describes an intended contribution, not a verified world-first claim. Before a paper, patent filing or commercial claim, compare the exact workflow with recent papers, open-source projects and vendor documentation, and record the search terms, dates and exclusions.

## References (starting points, not a literature review)

Elastic Observability · New Relic SRE Agent and Autopilot · Dynatrace Root Cause Analysis · Meta Engineering DrP · OpenTelemetry · Prometheus · Grafana Loki · FastAPI · PostgreSQL · Redis · Locust · Grafana k6 · DoWhy · AgentRCA preprint · Incident-Arena (verify exact title, authors and version before citing).

## License

To be decided.
