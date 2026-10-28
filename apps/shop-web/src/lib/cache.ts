// Catalogue query cache in front of the in-memory catalogue (the "origin"). Each get and set is a
// "cache.*" span. Lookups are best effort: a cache failure never fails the request, it falls
// back to the origin.
//
// S04 (cache unavailable): the cache node is unreachable, so every call waits for the client's
// timeout and fails. Requests still succeed, but each pays for the failed get and set.
import { activeScenario, InjectedFault, sleep } from "./faults";
import { withSpan } from "./trace";

export const CACHE_TIMEOUT_MS = 250;
const TTL_MS = 30_000;
const MAX_ENTRIES = 500;

export class CacheUnavailable extends InjectedFault {}

const store = new Map<string, { value: unknown; expires: number }>();

function call<T>(op: "get" | "set", fn: () => T): Promise<T> {
  return withSpan(`cache.${op} catalogue`, async () => {
    if (activeScenario() === "S04_cache_unavailable") {
      await sleep(CACHE_TIMEOUT_MS);
      throw new CacheUnavailable(`cache ${op} timed out after ${CACHE_TIMEOUT_MS}ms`);
    }
    return fn();
  }, { "cache.system": "memory" });
}

export async function cached<T>(key: string, load: () => T): Promise<T> {
  try {
    const hit = await call("get", () => {
      const entry = store.get(key);
      return entry && entry.expires > Date.now() ? (entry.value as T) : undefined;
    });
    if (hit !== undefined) return hit;
  } catch {
    // cache down: fall through to the origin
  }
  const value = load();
  try {
    await call("set", () => {
      if (store.size >= MAX_ENTRIES) store.delete(store.keys().next().value as string);
      store.set(key, { value, expires: Date.now() + TTL_MS });
    });
  } catch {
    // not cached this time; the next request tries again
  }
  return value;
}

export function clearCache(): void {
  store.clear();
}
