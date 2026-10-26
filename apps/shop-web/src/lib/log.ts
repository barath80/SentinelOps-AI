// Structured JSON logs written to stdout (Vercel Runtime Logs, or the local terminal) and,
// when SENTINEL_INGEST_URL is set, pushed to SentinelOps. Hobby-plan Vercel has no Log
// Drains, so pushing from the app is the portable path. Field names are stable:
// SentinelOps' `shop_json` adapter maps them to NormalizedEvent.
import { release } from "./faults";

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

let buffer: Record<string, unknown>[] = [];

export function log(level: LogLevel, message: string, fields: LogFields = {}): void {
  const record = {
    event_time: new Date().toISOString(),
    service_name: SERVICE,
    environment: process.env.VERCEL_ENV ?? process.env.NODE_ENV ?? "local",
    version: release(),
    level,
    message,
    ...fields,
  };
  const line = JSON.stringify(record);
  if (level === "error") console.error(line);
  else console.log(line);

  // Operator routes (fault toggles) are benchmark control traffic, not shop behavior.
  const isOperatorRoute = typeof fields.route === "string" && fields.route.startsWith("/api/admin");
  if (process.env.SENTINEL_INGEST_URL && !isOperatorRoute) {
    // Bounded: if SentinelOps is unreachable we drop the oldest rather than grow forever.
    if (buffer.length >= MAX_BUFFER) buffer.shift();
    buffer.push(record);
  }
}

// Operator-only record (e.g. which fault scenario was switched on). Console only, never
// pushed to SentinelOps: it is benchmark ground truth and must not reach the diagnosis agent.
export function auditLocal(message: string, fields: LogFields = {}): void {
  console.log(JSON.stringify({ event_time: new Date().toISOString(), audit: true, message, ...fields }));
}

// Sends buffered records. Never throws: telemetry must not break the shop.
export async function flushTelemetry(): Promise<void> {
  const url = process.env.SENTINEL_INGEST_URL;
  if (!url || buffer.length === 0) return;
  const batch = buffer;
  buffer = [];
  try {
    const res = await fetch(`${url.replace(/\/$/, "")}/api/v1/telemetry/events?adapter=shop_json`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${process.env.SENTINEL_INGEST_TOKEN ?? ""}`,
      },
      body: JSON.stringify({ events: batch }),
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) console.error(JSON.stringify({ message: "telemetry_push_failed", status: res.status }));
  } catch (err) {
    console.error(
      JSON.stringify({ message: "telemetry_push_error", error: err instanceof Error ? err.message : String(err) }),
    );
  }
}

export function newRequestId(request: Request): string {
  return request.headers.get("x-request-id") ?? crypto.randomUUID();
}
