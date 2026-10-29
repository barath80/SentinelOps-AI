import { tmpdir } from "node:os";
import { defineConfig, devices } from "@playwright/test";

// Browser test of the SentinelOps dashboard (services/sentinel-api/app/ui), run from here because
// this package already has Playwright. Starts a real API in operator mode on a throwaway SQLite
// file with test-only secrets:  npx playwright test -c playwright.dashboard.config.ts
const db = `${tmpdir().replace(/\\/g, "/")}/sentinel-dashboard-e2e-${Date.now()}.db`;

export default defineConfig({
  testDir: "./e2e-dashboard",
  workers: 1,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:8931", trace: "on-first-retry" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "python -m uvicorn app.asgi:app --port 8931",
    cwd: "../../services/sentinel-api",
    url: "http://127.0.0.1:8931/health",
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      SENTINEL_DATABASE_URL: `sqlite:///${db}`,
      SENTINEL_INGEST_TOKEN: "e2e-machine-token",
      SENTINEL_AUTH_MODE: "operators",
      SENTINEL_SESSION_SECRET: "e2e-session-secret-0123456789abcdef0123",
      SENTINEL_BOOTSTRAP_ADMIN: "admin:e2e-admin-password",
      SENTINEL_EXECUTOR: "mock",
      SENTINEL_NOTIFY_ALLOW_PRIVATE: "true", // the test channel points at 127.0.0.1
    },
  },
});
