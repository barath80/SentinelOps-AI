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

async function signIn(page: Page, username: string) {
  await page.goto("/ui/");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(`${username}-password-123`);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator("#whoami")).toContainText(`Signed in as ${username}`);
}

test("operators sign in, propose and approve with four eyes, and execute", async ({ page, request }) => {
  const problems: string[] = [];
  // Script errors and CSP violations ("Refused to ...") fail the test. HTTP error statuses are logged
  // by the browser too; the one expected here is the 403 for the responder's refused approval.
  page.on("console", (m) => { if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) problems.push(m.text()); });
  page.on("pageerror", (e) => problems.push(e.message));
  await operators(request);
  await seedBadRelease(request);

  await page.goto("/ui/");
  await expect(page.locator("#login")).toBeVisible();
  await expect(page.locator("#connect")).toBeHidden(); // the legacy token + name form is off in operator mode

  await signIn(page, "rita");
  await page.getByRole("button", { name: "Analyze now" }).click();
  await page.getByRole("button", { name: /api\/checkout: elevated 5xx errors/ }).click();
  await expect(page.getByRole("heading", { name: "Hypotheses (ranked)" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Failure propagation" })).toBeVisible();
  await expect(page.getByText(/Inferred from the service topology/)).toBeVisible();

  await page.getByRole("button", { name: "Propose recommended fix" }).click();
  await expect(page.getByRole("heading", { name: "Rehearsal (simulation)" })).toBeVisible();
  await expect(page.locator(".badge.AWAITING_APPROVAL")).toBeVisible();
  // a responder cannot approve, and nobody can approve their own proposal
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.locator("#status")).toContainText("role_approver_required");

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.locator("#login")).toBeVisible();
  await signIn(page, "abe");
  await page.getByRole("button", { name: /api\/checkout: elevated 5xx errors/ }).click();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.locator(".badge.READY_FOR_ACTION")).toBeVisible();
  await page.getByRole("button", { name: "Execute action" }).click();
  await expect(page.locator(".badge.VERIFYING")).toBeVisible();
  await page.getByText(/Audit trail/).click();
  await expect(page.getByText(/AWAITING_APPROVAL to READY_FOR_ACTION by abe/)).toBeVisible();

  expect(problems).toEqual([]); // no script errors and no CSP violations
});

test("a wrong password is refused and the machine token cannot sign in as a person", async ({ page, request }) => {
  await page.goto("/ui/");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator("#status")).toContainText("invalid_credentials");
  const asPerson = await request.post("/api/v1/recovery-contracts", { headers: MACHINE, data: { incident_id: "x" } });
  expect(asPerson.status()).toBe(403);
});
