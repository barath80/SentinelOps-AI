import { after } from "next/server";
import { flushTelemetry, log, newRequestId } from "./log";

type Ctx = { params: Promise<Record<string, string>> };
type Handler = (req: Request, ctx: Ctx, requestId: string) => Promise<Response>;

// Wraps a route handler: assigns a request id, times it, and emits one structured
// log line per request (info for <500, error for >=500 or thrown exceptions).
// Telemetry is flushed after the response so it never adds user-visible latency.
export function instrument(route: string, handler: Handler) {
  return async (req: Request, ctx: Ctx): Promise<Response> => {
    const requestId = newRequestId(req);
    const start = performance.now();
    after(flushTelemetry);
    try {
      const res = await handler(req, ctx, requestId);
      const duration_ms = Math.round(performance.now() - start);
      log(res.status >= 500 ? "error" : "info", "request", {
        request_id: requestId, route, method: req.method, status: res.status, duration_ms,
      });
      res.headers.set("x-request-id", requestId);
      return res;
    } catch (err) {
      const duration_ms = Math.round(performance.now() - start);
      log("error", "unhandled_exception", {
        request_id: requestId, route, method: req.method, status: 500, duration_ms,
        error: err instanceof Error ? err.message : String(err),
      });
      return Response.json({ error: "internal_error", request_id: requestId }, {
        status: 500, headers: { "x-request-id": requestId },
      });
    }
  };
}
