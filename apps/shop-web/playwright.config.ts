import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  // One worker: parallel tests against a cold dev server time out on slower machines.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3911",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev -- --port 3911",
    url: "http://localhost:3911",
    reuseExistingServer: false,
    timeout: 120_000,
    // SHOP_DB=memory: orders go to the in-memory store, so the journey needs no real database.
    env: { AUTH_SECRET: "e2e-test-secret-key-at-least-32-characters-long", SHOP_DB: "memory" },
  },
});
