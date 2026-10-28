import { AsyncLocalStorage } from "node:async_hooks";
import { clockOffsetMs } from "./faults";

// Minimal request tracing in OpenTelemetry's span shape. Each API request gets a trace; code can
// wrap work in withSpan() without passing ids around (AsyncLocalStorage carries the parent).
// Finished spans are handed to a sink (the telemetry pusher in log.ts).

export type SpanRecord = {
  traceId: string;
  spanId: string;
  parentSpanId?: string;
  name: string;
  serviceName: string;
  startTimeUnixNano: string; // uint64 as a string: epoch nanoseconds do not fit in a JS number
  endTimeUnixNano: string;
  status: { code: 0 | 1 | 2 }; // unset | ok | error
  attributes: Record<string, string | number | boolean>;
};

type Ctx = { traceId: string; spanId: string };
const store = new AsyncLocalStorage<Ctx>();
let sink: (s: SpanRecord) => void = () => {};

export function setSpanSink(fn: (s: SpanRecord) => void): void {
  sink = fn;
}

const randomHex = (bytes: number) =>
  Array.from(crypto.getRandomValues(new Uint8Array(bytes)), (b) => b.toString(16).padStart(2, "0")).join("");

function nowNanos(): bigint {
  const ms = performance.timeOrigin + performance.now() + clockOffsetMs();
  return BigInt(Math.floor(ms)) * BigInt(1_000_000) + BigInt(Math.round((ms % 1) * 1_000_000));
}

export function currentTraceId(): string | undefined {
  return store.getStore()?.traceId;
}

// Runs fn as the root span of a new trace and records it when fn settles.
export async function runTrace<T>(name: string, attributes: SpanRecord["attributes"], fn: (traceId: string) => Promise<T>,
                                  isError: (result: T) => boolean = () => false): Promise<T> {
  const ctx = { traceId: randomHex(16), spanId: randomHex(8) };
  const start = nowNanos();
  let failed = false;
  let result: T | undefined;
  try {
    result = await store.run(ctx, () => fn(ctx.traceId));
    failed = isError(result);
    return result;
  } catch (err) {
    failed = true;
    throw err;
  } finally {
    sink({ traceId: ctx.traceId, spanId: ctx.spanId, name, serviceName: "shop-web",
           startTimeUnixNano: start.toString(), endTimeUnixNano: nowNanos().toString(),
           status: { code: failed ? 2 : 1 }, attributes });
  }
}

// Records fn as a child span of the current span (no-op outside a trace).
export async function withSpan<T>(name: string, fn: () => Promise<T>, attributes: SpanRecord["attributes"] = {}): Promise<T> {
  const parent = store.getStore();
  if (!parent) return fn();
  const ctx = { traceId: parent.traceId, spanId: randomHex(8) };
  const start = nowNanos();
  let failed = false;
  try {
    return await store.run(ctx, fn);
  } catch (err) {
    failed = true;
    throw err;
  } finally {
    sink({ traceId: ctx.traceId, spanId: ctx.spanId, parentSpanId: parent.spanId, name, serviceName: "shop-web",
           startTimeUnixNano: start.toString(), endTimeUnixNano: nowNanos().toString(),
           status: { code: failed ? 2 : 1 }, attributes });
  }
}
