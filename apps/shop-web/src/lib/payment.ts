// Payment simulator. No real money and no card data: it only decides approve/decline
// from the order total, plus injected faults for benchmark scenarios.
import { activeScenario, InjectedFault, sleep } from "./faults";
import { withSpan } from "./trace";

export type PaymentResult =
  | { approved: true; authorizationId: string }
  | { approved: false; reason: "declined" };

export class PaymentTimeout extends InjectedFault {}
export class ProviderUnavailable extends InjectedFault {}

// S07: the provider is flaky. Most calls fail after a short wait with a transient error.
export const FLAKY_FAILURE_RATE = 0.75;
export const FLAKY_FAILURE_MS = 400;

// One call to the provider.
export async function authorize(totalCents: number, random: () => number = Math.random): Promise<PaymentResult> {
  const scenario = activeScenario();
  if (scenario === "S05_payment_timeout") {
    await sleep(3000);
    throw new PaymentTimeout("payment provider timed out after 3000ms");
  }
  if (scenario === "S07_retry_storm" && random() < FLAKY_FAILURE_RATE) {
    await sleep(FLAKY_FAILURE_MS);
    throw new ProviderUnavailable("payment provider returned 503 (transient)");
  }
  // Deterministic rule so tests are repeatable: totals over $5,000 are declined.
  if (totalCents > 500_000) return { approved: false, reason: "declined" };
  return { approved: true, authorizationId: `auth_${crypto.randomUUID()}` };
}

export const MAX_ATTEMPTS = 5;

// The client's retry policy: transient errors are retried immediately, up to MAX_ATTEMPTS, with
// no backoff and no jitter. Harmless while the provider is healthy; against a flaky provider it
// multiplies every failure into several calls (scenario S07, a retry storm). Each attempt is its
// own span, so the amplification is visible in traces. Timeouts are not retried.
export async function authorizeWithRetry(totalCents: number, onRetry: (attempt: number, error: Error) => void,
                                         random: () => number = Math.random): Promise<PaymentResult> {
  for (let attempt = 1; ; attempt++) {
    try {
      return await withSpan("payment.authorize", () => authorize(totalCents, random),
        { "payment.provider": "simulator", "payment.attempt": attempt });
    } catch (err) {
      if (!(err instanceof ProviderUnavailable) || attempt >= MAX_ATTEMPTS) throw err;
      onRetry(attempt, err);
    }
  }
}
