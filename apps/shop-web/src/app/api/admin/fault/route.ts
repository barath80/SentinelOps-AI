import { timingSafeEqual } from "node:crypto";
import { instrument } from "@/lib/handler";
import { activeScenario, isScenario, SCENARIOS, setOverride } from "@/lib/faults";
import { auditLocal } from "@/lib/log";

// Demo-only control. Fails closed: with no ADMIN_TOKEN configured every call is rejected.
function authorized(req: Request): boolean {
  const expected = process.env.ADMIN_TOKEN;
  const supplied = req.headers.get("x-admin-token");
  if (!expected || !supplied) return false;
  const a = Buffer.from(expected);
  const b = Buffer.from(supplied);
  return a.length === b.length && timingSafeEqual(a, b);
}

export const GET = instrument("/api/admin/fault", async (req) => {
  if (!authorized(req)) return Response.json({ error: "forbidden" }, { status: 403 });
  return Response.json({ active: activeScenario(), available: SCENARIOS });
});

// Body: { scenario: Scenario }. Applies to this server instance only (see lib/faults.ts).
export const POST = instrument("/api/admin/fault", async (req, _ctx, requestId) => {
  if (!authorized(req)) return Response.json({ error: "forbidden" }, { status: 403 });
  const body = (await req.json().catch(() => null)) as { scenario?: unknown } | null;
  if (!isScenario(body?.scenario)) return Response.json({ error: "unknown_scenario" }, { status: 400 });
  setOverride(body.scenario);
  auditLocal("fault_scenario_changed", { request_id: requestId, scenario: body.scenario });
  return Response.json({ active: activeScenario() });
});
