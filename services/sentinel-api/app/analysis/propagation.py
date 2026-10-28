"""Failure-propagation reconstruction and earliest containment, from recorded traces.

Nodes are the entry routes plus what their spans call: the connection pool, the database, the
payment provider, the cache, and the service's own compute (cpu_ms on the root span). For each
route -> dependency edge the per-request time and failure share are compared between the
baseline and the incident window. A node is anomalous when its time or failures clearly rose;
its onset is the first anomalous call. Ordering the anomalous nodes by onset gives the
propagation order, and the earliest anomalous dependency is where the failure could first have
been contained (a timeout, circuit breaker or failover on that edge).

Edges are labelled by their evidence: `observed` (spans in the incident window), `not_reached`
(called in the baseline but no longer called, for example code that now throws before the call),
`inferred` (declared in the static service topology but never seen in a span: its health is
unknown, it is never marked anomalous and never chosen as the containment point) or `no_traces`.
The result is temporal evidence from recorded spans, not a proof of causation.
"""
from __future__ import annotations

import statistics

from ..recovery.policy import DEPENDS_ON
from .detect import IncidentCandidate, Sample

MODEL_VERSION = "propagation-v1"
NOTE = "Temporal order of anomalies in recorded spans. Evidence of propagation, not proof of causation."
# span-name prefix -> dependency node (first match wins: the pool before the database)
TARGETS = [("db.pool", "postgres-pool"), ("db.", "postgres"), ("payment.", "payment-provider"), ("cache.", "cache")]
COMPUTE = "compute"
SERVICE = "shop-web"
# static topology names -> graph node names
TOPOLOGY_NODE = {"postgres": "postgres", "payment-simulator": "payment-provider", "cache": "cache"}
EVIDENCE = {"observed": "spans in the incident window", "not_reached": "spans in the baseline only",
            "inferred": "static topology only (no span)", "no_traces": "none: no request traces"}
MIN_RATIO, MIN_DELTA_MS, MIN_FAIL_SHARE = 2.0, 100.0, 0.5
CONTAIN = {"postgres-pool": "cap connection waits (acquire timeout) and shed load before the pool",
           "postgres": "put a query timeout on the slow statement",
           "payment-provider": "bound provider calls (timeout, capped retries, circuit breaker)",
           "cache": "fail fast on cache errors (short timeout or circuit breaker) instead of waiting",
           COMPUTE: "shed or rate-limit load before the CPU-bound work"}


def _target(name: str) -> str | None:
    return next((node for prefix, node in TARGETS if name.startswith(prefix)), None)


def build(cand: IncidentCandidate, samples: list[Sample], spans: dict[str, list]) -> dict:
    """spans: trace_id -> span rows (EventRow-like, attributes from the otel_span adapter)."""
    routes = sorted({s.route for s in samples if not s.route.startswith("/api/admin") and s.time <= cand.as_of})
    affected = set(cand.routes)
    onset_by_route = {a.route: a.onset for a in cand.anomalies}
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    traced_any = False

    for route in routes:
        reqs = [s for s in samples if s.route == route and s.time <= cand.as_of]
        nodes[route] = {"id": route, "kind": "route", "anomalous": route in affected,
                        "onset": onset_by_route[route].isoformat() if route in onset_by_route else None}
        # per request: dependency -> (ms, failed), plus compute
        per: dict[str, list[tuple[Sample, float, bool]]] = {}
        seen_base: set[str] = set()
        for s in reqs:
            kids = spans.get(s.trace_id or "", [])
            if not kids:
                continue
            traced_any = True
            acc: dict[str, list[float | bool]] = {}
            for sp in kids:
                a = sp.attributes or {}
                if not a.get("parent_span_id"):
                    cpu = a.get("cpu_ms")
                    if isinstance(cpu, (int, float)) and not isinstance(cpu, bool):
                        acc.setdefault(COMPUTE, [0.0, False])[0] += float(cpu)
                    continue
                node = _target(str(a.get("name", "")))
                if node is None:
                    continue
                cur = acc.setdefault(node, [0.0, False])
                cur[0] += float(a.get("duration_ms") or 0.0)
                cur[1] = cur[1] or a.get("status") == "error"
            for node, (ms, failed) in acc.items():
                per.setdefault(node, []).append((s, ms, failed))
                if s.time < cand.recent_start:
                    seen_base.add(node)
        for node in sorted(set(per) | seen_base):
            calls = per.get(node, [])
            base = [(s, ms, f) for s, ms, f in calls if s.time < cand.recent_start]
            recent = [(s, ms, f) for s, ms, f in calls if s.time >= cand.recent_start]
            edge = {"from": route, "to": node, "kind": "observed" if recent else "not_reached",
                    "baseline_calls": len(base), "recent_calls": len(recent), "anomalous": False, "onset": None}
            if recent and base:
                b_ms = statistics.median(ms for _, ms, _ in base)
                r_ms = statistics.median(ms for _, ms, _ in recent)
                b_fail = sum(f for *_, f in base) / len(base)
                r_fail = sum(f for *_, f in recent) / len(recent)
                slow = r_ms >= max(MIN_RATIO * b_ms, b_ms + MIN_DELTA_MS)
                failing = r_fail >= MIN_FAIL_SHARE and b_fail < 0.1
                edge.update({"baseline_median_ms": round(b_ms, 1), "recent_median_ms": round(r_ms, 1),
                             "baseline_failure_share": round(b_fail, 3), "recent_failure_share": round(r_fail, 3)})
                if slow or failing:
                    cut = max(b_ms * MIN_RATIO, b_ms + MIN_DELTA_MS)
                    first = min((s.time for s, ms, f in recent if f or ms >= cut), default=None)
                    edge.update({"anomalous": True, "onset": first.isoformat() if first else None,
                                 "symptom": "failing" if failing and not slow else "slow"})
            edges.append(edge)
            n = nodes.setdefault(node, {"id": node, "kind": "dependency" if node != COMPUTE else "compute",
                                        "anomalous": False, "onset": None})
            if edge["anomalous"] and route in affected:
                n["anomalous"] = True
                if edge["onset"] and (n["onset"] is None or edge["onset"] < n["onset"]):
                    n["onset"] = edge["onset"]

    if not traced_any:
        for route in routes:
            edges.append({"from": route, "to": None, "kind": "no_traces", "anomalous": False, "onset": None})
    seen = {e["to"] for e in edges if e["to"]}
    for dep in DEPENDS_ON.get(SERVICE, []):
        node = TOPOLOGY_NODE.get(dep, dep)
        if node not in seen:  # declared but unobserved: say so rather than guess its state
            edges.append({"from": SERVICE, "to": node, "kind": "inferred", "anomalous": None, "onset": None})
            nodes.setdefault(node, {"id": node, "kind": "dependency", "anomalous": None, "onset": None})
    for e in edges:
        e["evidence"] = EVIDENCE[e["kind"]]

    order = sorted((n for n in nodes.values() if n["anomalous"] and n["onset"]), key=lambda n: (n["onset"], n["kind"] == "route"))
    origin_deps = [n for n in order if n["kind"] != "route"]
    if origin_deps:
        first = origin_deps[0]
        containment = {"node": first["id"], "edge": [e["from"] for e in edges if e["to"] == first["id"] and e["anomalous"]],
                       "how": CONTAIN.get(first["id"], "isolate this dependency"),
                       "reason": f"{first['id']} is the earliest anomalous dependency on the affected routes"}
    elif order:
        containment = {"node": "service-code", "edge": [], "how": "stop or roll back the change on the affected routes",
                       "reason": "the affected routes fail while every traced dependency behaves as in the baseline"
                       if traced_any else "no traces: only the routes themselves are observed"}
    else:
        containment = None
    return {"model_version": MODEL_VERSION, "note": NOTE, "traced": traced_any, "nodes": list(nodes.values()),
            "edges": edges, "order": [n["id"] for n in order], "earliest_containment": containment}
