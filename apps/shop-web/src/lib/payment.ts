// Payment simulator. No real money and no card data: it only decides approve/decline
// from the order total, plus injected faults for benchmark scenarios.
import { activeScenario, InjectedFault, sleep } from "./faults";

export type PaymentResult =
  | { approved: true; authorizationId: string }
  | { approved: false; reason: "declined" };

export class PaymentTimeout extends InjectedFault {}

export async function authorize(totalCents: number): Promise<PaymentResult> {
  if (activeScenario() === "S05_payment_timeout") {
    await sleep(3000);
    throw new PaymentTimeout("payment provider timed out after 3000ms");
  }
  // Deterministic rule so tests are repeatable: totals over $5,000 are declined.
  if (totalCents > 500_000) return { approved: false, reason: "declined" };
  return { approved: true, authorizationId: `auth_${crypto.randomUUID()}` };
}
