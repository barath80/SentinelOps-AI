// Database connection gate. The Neon HTTP driver keeps no long-lived connections, so the shop
// models its connection limit as a bounded gate in front of each query: a request takes one of
// POOL_SIZE permits, waiting in a "db.pool.acquire" span when none is free.
//
// S02 (pool exhaustion): connections leak and are never returned. Each acquire then waits until
// the client's acquire timeout reclaims a connection, so time goes into waiting for a
// connection while the queries themselves stay fast.
import { activeScenario, sleep } from "./faults";
import { withSpan } from "./trace";

export const POOL_SIZE = 10;
export const ACQUIRE_TIMEOUT_MS = 1300;

let free = POOL_SIZE;
const waiters: (() => void)[] = [];

async function acquire(): Promise<void> {
  if (activeScenario() === "S02_db_pool_exhaustion") {
    await sleep(ACQUIRE_TIMEOUT_MS); // every connection is leaked: wait out the timeout, then reclaim one
    return;
  }
  if (free > 0) {
    free -= 1;
    return;
  }
  await new Promise<void>((resolve) => waiters.push(resolve));
}

function release(): void {
  const next = waiters.shift();
  if (next) next();
  else free = Math.min(POOL_SIZE, free + 1);
}

export async function withConnection<T>(fn: () => Promise<T>): Promise<T> {
  const exhausted = activeScenario() === "S02_db_pool_exhaustion";
  await withSpan("db.pool.acquire", acquire, { "db.system": "postgresql", "db.pool.size": POOL_SIZE });
  try {
    return await fn();
  } finally {
    if (!exhausted) release();
  }
}

export function poolStats(): { free: number; waiting: number } {
  return { free, waiting: waiters.length };
}
