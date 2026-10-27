import { afterEach, describe, expect, it, vi } from "vitest";
import { activeScenario, release, runWithScenario, scenarioFromHeaders } from "./faults";

const TOKEN = "a-sufficiently-long-chaos-token";
const headers = (h: Record<string, string>) => new Headers(h);

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("scenarioFromHeaders (scoped chaos)", () => {
  it("returns the scenario for a valid token", () => {
    vi.stubEnv("CHAOS_TOKEN", TOKEN);
    expect(scenarioFromHeaders(headers({ "x-chaos-token": TOKEN, "x-chaos-scenario": "S01_bad_deployment" }))).toBe("S01_bad_deployment");
  });

  it("fails closed: no CHAOS_TOKEN configured means headers are ignored", () => {
    vi.stubEnv("CHAOS_TOKEN", "");
    expect(scenarioFromHeaders(headers({ "x-chaos-token": "", "x-chaos-scenario": "S01_bad_deployment" }))).toBeUndefined();
  });

  it("ignores a configured token that is too short to be a secret", () => {
    vi.stubEnv("CHAOS_TOKEN", "short");
    expect(scenarioFromHeaders(headers({ "x-chaos-token": "short", "x-chaos-scenario": "S01_bad_deployment" }))).toBeUndefined();
  });

  it("ignores a wrong or missing token", () => {
    vi.stubEnv("CHAOS_TOKEN", TOKEN);
    expect(scenarioFromHeaders(headers({ "x-chaos-token": TOKEN.replace("a", "b"), "x-chaos-scenario": "S01_bad_deployment" }))).toBeUndefined();
    expect(scenarioFromHeaders(headers({ "x-chaos-scenario": "S01_bad_deployment" }))).toBeUndefined();
  });

  it("ignores unknown scenario names", () => {
    vi.stubEnv("CHAOS_TOKEN", TOKEN);
    expect(scenarioFromHeaders(headers({ "x-chaos-token": TOKEN, "x-chaos-scenario": "rm -rf /" }))).toBeUndefined();
  });
});

describe("runWithScenario", () => {
  it("applies the fault only inside its own request", async () => {
    vi.stubEnv("FAULT_SCENARIO", "none");
    const inside = await runWithScenario("S08_plain_errors", async () => activeScenario());
    expect(inside).toBe("S08_plain_errors");
    expect(activeScenario()).toBe("none");
  });

  it("keeps concurrent requests isolated", async () => {
    const tick = () => new Promise((r) => setTimeout(r, 5));
    const [a, b] = await Promise.all([
      runWithScenario("S01_bad_deployment", async () => { await tick(); return [activeScenario(), release()]; }),
      runWithScenario(undefined, async () => { await tick(); return [activeScenario(), release()]; }),
    ]);
    expect(a).toEqual(["S01_bad_deployment", "v2"]);
    expect(b[0]).toBe("none");
    expect(b[1]).not.toBe("v2");
  });
});
