import { after } from "next/server";
import { flushTelemetry, log, newRequestId } from "./log";
import { activeScenario, burnCpu, CPU_BURN_MS, runWithScenario, scenarioFromHeaders } from "./faults";
import { runTrace } from "./trace";

type Ctx = { params: Promise<Record<string, string>> };
type Handler = (req: Request, ctx: Ctx, requestId: string) => Promise<Response>;

// Wraps a route handler: assigns a request id, runs it as the root span of a trace, times it,
// and emits one structured log line per request (info for <500, error for >=500 or thrown
// exceptions) carrying the trace id. Telemetry is flushed after the response so it never adds
// user-visible latency.
export function instrument(route: string, handler: Handler) {
  return async (req: Request, ctx: Ctx): Promise<Response> => {
    const requestId = newRequestId(req);
    const start = performance.now();
    after(flushTelemetry);
    const attrs: Record<string, string | number> = { "http.route": route, "http.method": req.method };
    // A scoped chaos fault (see lib/faults.ts) applies to this request only and is never logged.
    const scenario = scenarioFromHeaders(req.headers);
    // On-CPU time of this request (user + system), recorded on the root span. On a serverless
    // instance that serves one request at a time this is the request's own CPU time.
    const cpuStart = process.cpuUsage();
    const recordCpu = () => {
      const used = process.cpuUsage(cpuStart);
      attrs["cpu_ms"] = Math.round((used.user + used.system) / 1000);
    };
    return runWithScenario(scenario, () => runTrace(`${req.method} ${route}`, attrs, async () => {
      try {
        if (activeScenario() === "S06_cpu_saturation") burnCpu(CPU_BURN_MS);
        const res = await handler(req, ctx, requestId);
        const duration_ms = Math.round(performance.now() - start);
        recordCpu();
        attrs["http.status_code"] = res.status;
        log(res.status >= 500 ? "error" : "info", "request", {
          request_id: requestId, route, method: req.method, status: res.status, duration_ms,
        });
        res.headers.set("x-request-id", requestId);
        return res;
      } catch (err) {
        const duration_ms = Math.round(performance.now() - start);
        recordCpu();
        attrs["http.status_code"] = 500;
        log("error", "unhandled_exception", {
          request_id: requestId, route, method: req.method, status: 500, duration_ms,
          error: err instanceof Error ? err.message : String(err),
        });
        return Response.json({ error: "internal_error", request_id: requestId }, {
          status: 500, headers: { "x-request-id": requestId },
        });
      }
    }, (res) => res.status >= 500));
  };
}
