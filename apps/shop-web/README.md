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
- Faults are off by default. `FAULT_SCENARIO` (or `POST /api/admin/fault` with `x-admin-token`) selects one of: `S01_bad_deployment` (checkout 500s, release label changes to `v2`), `S03_slow_query` (+1.5 s checkout), `S05_payment_timeout` (504 after 3 s).
- Ground truth stays out of telemetry: the scenario name is written only to the local console, and `/api/admin` requests are never pushed.
- The admin override is per server instance. On serverless, use the `FAULT_SCENARIO` env var until a durable store exists.

## Known limits

- Orders live in Neon Postgres (`DATABASE_URL` in `.env.local`; create the table with `npm run db:migrate`). The fault-scenario override is still per server instance.
- Unknown product pages return HTTP 200 with a not-found body because the page streams inside Suspense.
