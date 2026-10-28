# ShopSphere (shop-web)

Synthetic demo shop used as a workload for SentinelOps AI. Next.js (App Router), deployable to Vercel as-is. No real payments or personal data.

## Run locally

    npm install
    npm run dev        # http://localhost:3000

## What exists (Phase 1)

- Pages: catalogue + search, product detail, cart, order confirmation
- API: `/api/products`, `/api/products/[id]`, `/api/cart`, `/api/checkout`, `/api/orders/[id]`, `/api/health`
- Cart is a cookie (stateless). Checkout requires an `Idempotency-Key` header; replays return the same order.
- Payment simulator: deterministic approve/decline, no card data
- Every API request emits one structured JSON log line (`request_id`, `route`, `status`, `duration_ms`, `service_name`, `version`)

## Phase 2: telemetry and fault injection

- Set `SENTINEL_INGEST_URL` and `SENTINEL_INGEST_TOKEN` and the shop pushes its structured log lines to `services/sentinel-api` after each response (works on Vercel Hobby, which has no Log Drains). Copy `.env.example` to `.env.local`.
- Faults are off by default. `FAULT_SCENARIO` (or `POST /api/admin/fault` with `x-admin-token`, or the scoped `x-chaos-token` + `x-chaos-scenario` headers) selects one of:

  | Scenario | Behaviour |
  | --- | --- |
  | `S01_bad_deployment` | checkout throws (500), release label changes to `v2` |
  | `S02_db_pool_exhaustion` | every checkout query waits out the 1.3 s connection-acquire timeout (`src/lib/pool.ts`) |
  | `S03_slow_query` | +1.5 s inside the checkout lookup query |
  | `S04_cache_unavailable` | catalogue cache get and set time out after 250 ms each; results come from the origin (`src/lib/cache.ts`) |
  | `S05_payment_timeout` | the payment provider hangs 3 s, checkout returns 504 |
  | `S06_cpu_saturation` | every request burns 700 ms of CPU on the event loop |
  | `S07_retry_storm` | the provider fails 75% of calls after 400 ms; the client retries immediately up to 5 times, 502 when all fail |
  | `S08_plain_errors` | checkout returns plain 500s with no other signal |
  | `S11_clock_skew` | the service is healthy, but telemetry timestamps run 4 minutes ahead |
- Each API request is traced (`src/lib/trace.ts`): a root span (with the request's on-CPU time as `cpu_ms`) plus child spans for connection acquisition, database queries, each payment attempt and cache calls, pushed to SentinelOps with the `otel_span` adapter; log lines carry the `trace_id`. Fault S03's delay happens inside the database span, like a real slow query.
- Ground truth stays out of telemetry: the scenario name is written only to the local console, and `/api/admin` requests are never pushed.
- The admin override is per server instance. On serverless, use the `FAULT_SCENARIO` env var until a durable store exists.

## Known limits

- Orders live in Neon Postgres (`DATABASE_URL` in `.env.local`; create the table with `npm run db:migrate`). The fault-scenario override is still per server instance.
- Unknown product pages return HTTP 200 with a not-found body because the page streams inside Suspense.
