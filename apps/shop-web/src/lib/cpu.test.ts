import { describe, expect, it } from "vitest";
import { burnCpu } from "./faults";
import { beginCpu, endCpu } from "./cpu";

describe("per-request CPU time", () => {
  it("is recorded for a request that ran alone", () => {
    const t = beginCpu();
    burnCpu(20);
    const ms = endCpu(t);
    expect(ms).toBeGreaterThanOrEqual(10);
  });

  it("is not recorded when requests overlap, since the reading is process-wide", () => {
    const a = beginCpu();
    const b = beginCpu(); // started while a was running
    expect(endCpu(a)).toBeUndefined();
    expect(endCpu(b)).toBeUndefined();
    const c = beginCpu(); // alone again
    expect(endCpu(c)).toBeTypeOf("number");
  });

  it("counts a request once even if ended twice", () => {
    const t = beginCpu();
    expect(endCpu(t)).toBeTypeOf("number");
    expect(endCpu(t)).toBeUndefined();
    expect(endCpu(beginCpu())).toBeTypeOf("number"); // the in-flight count was not decremented twice
  });
});
