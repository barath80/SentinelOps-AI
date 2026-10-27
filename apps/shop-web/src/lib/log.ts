// Structured JSON logs written to stdout (Vercel Runtime Logs, or the local terminal) and,
// when SENTINEL_INGEST_URL is set, pushed to SentinelOps together with request trace spans.
// Hobby-plan Vercel has no Log Drains, so pushing from the app is the portable path. Field names
// are stable: SentinelOps' `shop_json` and `otel_span` adapters map them to NormalizedEvent.
import { release } from "./faults";
import { currentTraceId, setSpanSink, type SpanRecord } from "./trace";

export type LogLevel = "info" | "warning" | "error";

export type LogFields = {
  request_id?: string;
  route?: string;
  duration_ms?: number;
  status?: number;
  [key: string]: unknown;
};

const SERVICE = "shop-web";
const MAX_BUFFER = 200;

let logBuffer: Record<string, unknown>[] = [];
let spanBuffer: SpanRecord[] = [];

const pushing = () => !!process.env.SENTINEL_INGEST_URL;
// Operator routes (fault toggles) are benchmark control traffic, not shop behaviour.
const isOperator = (route: unknown) => typeof route === "string" && route.startsWith("/api/admin");

// Bounded buffers: if SentinelOps is unreachable we drop the oldest rather than grow forever.
function bounded<T>(buf: T[], item: T): void {
  if (buf.length >= MAX_BUFFER) buf.shift();
  buf.push(item);
}

setSpanSink((span) => {
  if (pushing() && !isOperator(span.attributes["http.route"])) bounded(spanBuffer, span);
});

export function log(level: LogLevel, message: string, fields: LogFields = {}): void {
  const traceId = currentTraceId();
  const record = {
    event_time: new Date().toISOString(),
    service_name: SERVICE,
    environment: process.env.VERCEL_ENV ?? process.env.NODE_ENV ?? "local",
    version: release(),
    level,
    message,
    ...(traceId ? { trace_id: traceId } : {}),
    ...fields,
  };
  const line = JSON.stringify(record);
  if (level === "error") console.error(line);
  else console.log(line);
  if (pushing() && !isOperator(fields.route)) bounded(logBuffer, record);
}

// Operator-only record (e.g. which fault scenario was switched on). Console only, never
// pushed to SentinelOps: it is benchmark ground truth and must not reach the diagnosis agent.
export function auditLocal(message: string, fields: LogFields = {}): void {
  console.log(JSON.stringify({ event_time: new Date().toISOString(), audit: true, message, ...fields }));
}

async function send(adapter: string, events: unknown[]): Promise<void> {
  const url = process.env.SENTINEL_INGEST_URL!;
  try {
    const res = await fetch(`${url.replace(/\/$/, "")}/api/v1/telemetry/events?adapter=${adapter}`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${process.env.SENTINEL_INGEST_TOKEN ?? ""}` },
      body: JSON.stringify({ events }),
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) console.error(JSON.stringify({ message: "telemetry_push_failed", adapter, status: res.status }));
  } catch (err) {
    console.error(JSON.stringify({ message: "telemetry_push_error", adapter, error: err instanceof Error ? err.message : String(err) }));
  }
}

// Sends buffered logs and spans. Never throws: telemetry must not break the shop.
export async function flushTelemetry(): Promise<void> {
  if (!pushing()) return;
  const logs = logBuffer;
  const spans = spanBuffer;
  logBuffer = [];
  spanBuffer = [];
  await Promise.all([logs.length ? send("shop_json", logs) : null, spans.length ? send("otel_span", spans) : null]);
}

export function newRequestId(request: Request): string {
  return request.headers.get("x-request-id") ?? crypto.randomUUID();
}
