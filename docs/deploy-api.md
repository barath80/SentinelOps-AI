# Deploying the SentinelOps API

Status: **prepared and partly verified, not deployed.** Verified: the app against real Neon Postgres (full flow), the runtime
dependency list in a clean virtualenv, and the container start command run locally. **Not verified:** building the Docker image
(Docker was not available) and running on Render.

## Steps (Render, free tier)

1. **Database.** Use a Postgres connection string (for example a Neon branch or database separate from the shop's). The API creates
   its own tables on first start (`events`, `incidents`, `hypotheses`, `evidence`, `diagnostic_runs`, `recovery_contracts`,
   `contract_transitions`, `approvals`, `action_runs`, `verification_runs`). It never touches the shop's `orders` table.
2. **Create the service.** In Render choose New > Blueprint, select this repository, and apply `render.yaml`. Set:
   - `SENTINEL_DATABASE_URL`: the Postgres URL (`postgresql://` or `postgres://` both work).
   - `SENTINEL_INGEST_TOKEN`: a long random secret (`openssl rand -hex 24`).
3. **Check it.** `https://<service>.onrender.com/health` returns `{"status":"ok"}`. Open `/ui/`, enter the token and your name.
4. **Connect the shop.** In the shop's Vercel project set `SENTINEL_INGEST_URL=https://<service>.onrender.com` and
   `SENTINEL_INGEST_TOKEN=<the same secret>`, then redeploy.
5. **Analyze.** Incidents appear when you press "Analyze now" in the dashboard (or `POST /api/v1/incidents/analyze`). There is no
   scheduler yet.

## Known limits to accept before relying on it

- **Free instances sleep.** The shop gives up on a push after 3 s and drops the events, so telemetry sent while the API is
  waking up is lost. Use a paid instance or a keep-alive if that matters.
- **No data retention.** The `events` table grows without limit. Add a retention job before leaving it running on a small database.
- **Schema changes are not migrated.** `create_all` only creates missing tables. Changing a column needs a real migration
  (Alembic); until then drop and recreate the SentinelOps tables.
- **One shared secret, one tenant.** The bearer token grants full access, including approving and executing actions. Actor names
  are asserted by the caller, not authenticated. Do not expose a deployment with a real executor until real login exists.
- **Executor is `mock`.** Approving and "executing" only records the action. `shop_admin` needs `SENTINEL_SHOP_ADMIN_URL` and
  `SENTINEL_SHOP_ADMIN_TOKEN` and changes the demo shop's fault state, so use it only against a demo shop.
- **No rate limiting** on the API.
