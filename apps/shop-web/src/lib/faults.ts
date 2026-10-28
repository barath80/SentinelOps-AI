import { AsyncLocalStorage } from "node:async_hooks";
import { timingSafeEqual } from "node:crypto";

// Fault injection for the demo/benchmark. Faults are OFF unless a scenario is selected.
//
// Three ways to select one, most specific first:
//  1. Scoped (preferred on a public deployment): a request carrying `x-chaos-token` equal to
//     CHAOS_TOKEN and `x-chaos-scenario` gets that fault, and ONLY that request. Real visitors
//     never see it. Works on serverless because nothing is shared between instances.
//  2. In-memory override via /api/admin/fault (local use; per instance on serverless).
//  3. The FAULT_SCENARIO env var (affects every request; needs a redeploy to change).
// The chaos headers are never logged or pushed to SentinelOps: they are ground truth.

export type Scenario =
  | "none" | "S01_bad_deployment" | "S02_db_pool_exhaustion" | "S03_slow_query" | "S04_cache_unavailable"
  | "S05_payment_timeout" | "S06_cpu_saturation" | "S07_retry_storm" | "S08_plain_errors" | "S11_clock_skew";

export const SCENARIOS: Scenario[] = [
  "none", "S01_bad_deployment", "S02_db_pool_exhaustion", "S03_slow_query", "S04_cache_unavailable",
  "S05_payment_timeout", "S06_cpu_saturation", "S07_retry_storm", "S08_plain_errors", "S11_clock_skew",
];

let override: Scenario | undefined;
const scoped = new AsyncLocalStorage<Scenario>();

export function isScenario(value: unknown): value is Scenario {
  return typeof value === "string" && (SCENARIOS as string[]).includes(value);
}

export function setOverride(s: Scenario | undefined): void {
  override = s;
}

// The scenario a request asked for through the chaos headers, or undefined. Fails closed: with no
// CHAOS_TOKEN configured, or a wrong token, the headers are ignored.
export function scenarioFromHeaders(headers: Headers): Scenario | undefined {
  const expected = process.env.CHAOS_TOKEN;
  const supplied = headers.get("x-chaos-token");
  const wanted = headers.get("x-chaos-scenario");
  if (!expected || expected.length < 16 || !supplied || !isScenario(wanted)) return undefined;
  const a = Buffer.from(expected);
  const b = Buffer.from(supplied);
  return a.length === b.length && timingSafeEqual(a, b) ? wanted : undefined;
}

export function runWithScenario<T>(scenario: Scenario | undefined, fn: () => Promise<T>): Promise<T> {
  return scenario ? scoped.run(scenario, fn) : fn();
}

export function activeScenario(): Scenario {
  const s = scoped.getStore();
  if (s) return s;
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

// S11: this instance's clock runs ahead. Telemetry timestamps use it; nothing else changes.
export const CLOCK_AHEAD_MS = 240_000;

export function clockOffsetMs(): number {
  return activeScenario() === "S11_clock_skew" ? CLOCK_AHEAD_MS : 0;
}

export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

// S06: the instance is CPU-saturated. Every request spends this long computing on the event loop.
export const CPU_BURN_MS = 700;

export function burnCpu(ms: number): number {
  const end = performance.now() + ms;
  let x = 1;
  while (performance.now() < end) x = (x * 48271) % 2147483647; // busy work the optimizer cannot drop
  return x;
}

export class InjectedFault extends Error {}
