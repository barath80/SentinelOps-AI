import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const MACHINE = { authorization: "Bearer e2e-machine-token" };

function line(t: Date, route: string, status: number, duration: number, extra: Record<string, unknown> = {}) {
  return {
    event_time: t.toISOString(), service_name: "shop-web", environment: "production", level: status >= 500 ? "error" : "info",
    version: "v1", message: "request", request_id: `r-${t.getTime()}-${route}`, route, method: "POST", status, duration_ms: duration, ...extra,
  };
}

// A healthy baseline, then a bad release that makes checkout throw (scenario S01).
async function seedBadRelease(request: APIRequestContext) {
  const now = Date.now();
  const events = [];
  for (let i = 0; i < 60; i++) {
    const t = new Date(now - (600 - i * 7) * 1000);
    events.push(line(t, "/api/checkout", 201, 18 + (i % 5)), line(new Date(t.getTime() + 1000), "/api/products", 200, 9));
  }
  for (let i = 0; i < 10; i++) {
    const t = new Date(now - (100 - i * 9) * 1000);
    events.push(line(t, "/api/checkout", 500, 2, { version: "v2", message: "unhandled_exception", error: "TypeError: x" }),
                line(new Date(t.getTime() + 1000), "/api/products", 200, 9, { version: "v2" }));
  }
  const res = await request.post("/api/v1/telemetry/events?adapter=shop_json", { headers: MACHINE, data: { events } });
  expect((await res.json()).rejected).toBe(0);
}

async function operators(request: APIRequestContext) {
  const login = await request.post("/api/v1/auth/login", { data: { username: "admin", password: "e2e-admin-password" } });
  const admin = { authorization: `Bearer ${(await login.json()).token}` };
  for (const [username, role] of [["rita", "responder"], ["abe", "approver"]]) {
    const r = await request.post("/api/v1/operators", { headers: admin, data: { username, password: `${username}-password-123`, role } });
    expect([201, 409]).toContain(r.status());
  }
}

async function signIn(page: Page, username: string, password = `${username}-password-123`) {
  await page.goto("/ui/");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator("#whoami")).toContainText(`Signed in as ${username}`);
}

function watchErrors(page: Page): string[] {
  const problems: string[] = [];
  // Script errors and CSP violations ("Refused to ...") fail the test. HTTP error statuses are logged by
  // the browser too; the expected ones here are the 403s for deliberately refused actions.
  page.on("console", (m) => { if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) problems.push(m.text()); });
  page.on("pageerror", (e) => problems.push(e.message));
  return problems;
}

const incidentButton = (page: Page) => page.getByRole("button", { name: /api\/checkout: elevated 5xx errors/ }).first();

test("operators sign in, investigate with evidence, and recover with four eyes", async ({ page, request }) => {
  const problems = watchErrors(page);
  await operators(request);
  await seedBadRelease(request);

  await page.goto("/ui/");
  await expect(page.locator("#login")).toBeVisible();
  await expect(page.locator("#connect")).toBeHidden(); // the legacy token form is off in operator mode

  await signIn(page, "rita");
  await expect(page.getByRole("heading", { name: "Service health" })).toBeVisible();
  await page.getByRole("button", { name: "Analyze now" }).click();
  await expect(incidentButton(page)).toBeVisible();
  await incidentButton(page).click();

  // summary: propagation graph with the inferred edges called out
  await expect(page.getByRole("heading", { name: "Failure propagation" })).toBeVisible();
  await expect(page.getByText(/Inferred from the service topology/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Similar past incidents" })).toBeVisible();
  // timeline: the incident's story in order, with the release that preceded it
  await page.getByRole("tab", { name: "Timeline" }).click();
  await expect(page.getByRole("heading", { name: "What happened, in order" })).toBeVisible();
  await expect(page.getByText(/release v2 first seen/)).toBeVisible();
  // postmortem draft from stored evidence
  await page.getByRole("button", { name: "Postmortem draft" }).click();
  await expect(page.locator("#drawer-body")).toContainText("## Root cause and evidence");
  await expect(page.getByRole("button", { name: "Download .md" })).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();
  // evidence: every citation opens its source event
  await page.getByRole("tab", { name: "Evidence" }).click();
  await expect(page.getByRole("heading", { name: "Hypotheses (ranked)" })).toBeVisible();
  await page.locator("button.ref").first().click();
  await expect(page.locator("#drawer")).toBeVisible();
  await expect(page.locator("#drawer-body")).toContainText("event_id");
  await page.getByRole("button", { name: "Close" }).click();
  // logs, traces and metrics of this incident
  await page.getByRole("tab", { name: "Logs, traces, metrics" }).click();
  await expect(page.getByRole("heading", { name: "Error rate" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Failing and slow requests" })).toBeVisible();
  // the learned model explains itself
  await page.getByRole("tab", { name: "ML model" }).click();
  await expect(page.getByRole("heading", { name: "Learned model (shadow)" })).toBeVisible();

  // manual recovery: the responder proposes but cannot approve
  await page.getByRole("tab", { name: "Recovery" }).click();
  await page.getByRole("button", { name: "Propose recommended fix" }).click();
  await expect(page.getByRole("heading", { name: "Rehearsal (simulation)" })).toBeVisible();
  await expect(page.locator(".badge.AWAITING_APPROVAL")).toBeVisible();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.locator("#toasts")).toContainText("role_approver_required");

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.locator("#login")).toBeVisible();
  await signIn(page, "abe");
  await page.getByRole("button", { name: /^Incidents/ }).click();
  await incidentButton(page).click();
  await page.getByRole("tab", { name: "Recovery" }).click();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.locator(".badge.READY_FOR_ACTION")).toBeVisible();
  await page.getByRole("button", { name: "Execute action" }).click();
  await expect(page.locator(".badge.VERIFYING")).toBeVisible();
  await page.getByText(/Audit trail/).click();
  await expect(page.getByText(/AWAITING_APPROVAL to READY_FOR_ACTION/)).toBeVisible();
  await expect(page.locator(".timeline")).toContainText("by abe");

  expect(problems).toEqual([]);
});

test("admins configure automation, notifications and operators; everything is audited", async ({ page, request }) => {
  const problems = watchErrors(page);
  await operators(request);
  await signIn(page, "admin", "e2e-admin-password");

  await page.getByRole("button", { name: /^Automation/ }).click();
  await expect(page.getByRole("heading", { name: "Automatic remediation" })).toBeVisible();
  await page.getByLabel("Mode for payment_provider_timeout").selectOption("propose");
  await page.getByRole("row", { name: /payment provider timeout/ }).getByRole("button", { name: "Save" }).click();
  await expect(page.locator("#toasts")).toContainText("Save policy: done");

  await page.getByRole("button", { name: /^Notifications/ }).click();
  await page.getByLabel("Channel name").fill("#oncall");
  await page.getByLabel("Webhook URL").fill("http://127.0.0.1:9/hook");
  await page.getByRole("button", { name: "Add channel" }).click();
  await expect(page.locator("#drawer")).toContainText("Signing secret");
  await page.getByRole("button", { name: "Close" }).click();
  await expect(page.getByRole("cell", { name: "#oncall" })).toBeVisible();

  await page.getByRole("button", { name: /^Operators/ }).click();
  await expect(page.getByRole("cell", { name: "rita", exact: true })).toBeVisible();

  await page.getByRole("button", { name: /^Telemetry/ }).click();
  await page.getByRole("tab", { name: "Logs" }).click();
  await expect(page.getByLabel("Search logs")).toBeVisible();
  await page.getByRole("button", { name: /^ML model/ }).click();
  await expect(page.getByRole("heading", { name: "Serving model" })).toBeVisible();
  await page.getByRole("button", { name: /^SLOs/ }).click();
  await expect(page.getByRole("heading", { name: "Service level objectives" })).toBeVisible();

  await page.getByRole("button", { name: /^Audit log/ }).click();
  await expect(page.getByText("automation.policy_changed")).toBeVisible();
  await expect(page.getByText("notification.channel_added")).toBeVisible();

  await page.setViewportSize({ width: 390, height: 800 }); // phone: the sidebar becomes a menu
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.locator("#sidebar")).toHaveClass(/open/);

  expect(problems).toEqual([]);
});

test("a wrong password is refused and the machine token cannot act as a person", async ({ page, request }) => {
  await page.goto("/ui/");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator("#login-status")).toContainText("invalid_credentials");
  const asPerson = await request.post("/api/v1/recovery-contracts", { headers: MACHINE, data: { incident_id: "x" } });
  expect(asPerson.status()).toBe(403);
});
