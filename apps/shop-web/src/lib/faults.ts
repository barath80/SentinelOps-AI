// Fault injection for the demo/benchmark. Faults are OFF unless a scenario is selected.
// Never enable on a deployment that serves real users.

export type Scenario = "none" | "S01_bad_deployment" | "S03_slow_query" | "S05_payment_timeout";

export const SCENARIOS: Scenario[] = ["none", "S01_bad_deployment", "S03_slow_query", "S05_payment_timeout"];

// Source of truth is the FAULT_SCENARIO env var (works on every host). An in-memory override
// set via /api/admin/fault is convenient locally, but on serverless it only affects the
// instance that received the call, so a durable store replaces it later.
let override: Scenario | undefined;

export function isScenario(value: unknown): value is Scenario {
  return typeof value === "string" && (SCENARIOS as string[]).includes(value);
}

export function setOverride(s: Scenario | undefined): void {
  override = s;
}

export function activeScenario(): Scenario {
  if (override) return override;
  const fromEnv = process.env.FAULT_SCENARIO;
  return isScenario(fromEnv) ? fromEnv : "none";
}

// Release label reported in logs. S01 simulates a new deploy; the label must look like any
// ordinary release, because telemetry is what the diagnosis agent sees (no ground-truth leaks).
export function release(): string {
  if (activeScenario() === "S01_bad_deployment") return "v2";
  return process.env.VERCEL_GIT_COMMIT_SHA?.slice(0, 7) ?? "v1";
}

export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export class InjectedFault extends Error {}
