import { afterEach, describe, expect, it, vi } from "vitest";
import { setOverride } from "./faults";
import { authorize, PaymentTimeout } from "./payment";

afterEach(() => {
  setOverride(undefined);
  vi.useRealTimers();
});

describe("authorize", () => {
  it("approves totals at or below $5,000", async () => {
    const result = await authorize(500_000);
    expect(result).toMatchObject({ approved: true });
  });

  it("declines totals over $5,000", async () => {
    const result = await authorize(500_001);
    expect(result).toEqual({ approved: false, reason: "declined" });
  });

  it("throws PaymentTimeout when the S05 fault scenario is active", async () => {
    vi.useFakeTimers();
    setOverride("S05_payment_timeout");
    const pending = authorize(1000);
    const assertion = expect(pending).rejects.toBeInstanceOf(PaymentTimeout);
    await vi.advanceTimersByTimeAsync(3000);
    await assertion;
  });
});
