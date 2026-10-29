"""Parametric incident generator for training the root-cause classifier.

Unlike the benchmark (a few fixed fault shapes), every sample here draws its own traffic level,
latencies, noise, cold-start outliers, missing logs, partial severity and decoy deployments, so
the classes overlap the way real incidents do. Requests may carry traces shaped like the real shop's
(pool, query, payment and cache child spans, on-CPU time on the root span), with partial and
sometimes no tracing, so causes that look alike in logs can be told apart only when traces exist.
Two distributions are provided:

  standard  the training distribution
  shifted   harder and different: sparser traffic, more noise, more decoys, more missing logs,
            weaker signals. Used only for testing, to measure robustness to distribution shift.

The label is returned separately and is never part of the telemetry.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
CLASSES = ["release_regression", "payment_provider_timeout", "slow_dependency", "traffic_surge", "db_pool_exhaustion",
           "cache_unavailable", "resource_saturation", "retry_storm", "unknown"]


@dataclass(frozen=True)
class Dist:
    n_base: tuple[int, int]
    n_recent: tuple[int, int]
    jitter: tuple[float, float]
    outlier_p: float
    base_err: tuple[float, float]
    decoy_p: float
    drop: tuple[float, float]
    severity: tuple[float, float]
    exc_p: tuple[float, float]
    timeout_log_p: tuple[float, float]
    slow_extra: tuple[float, float]
    surge_mult: tuple[float, float]
    trace_p: tuple[float, float]  # share of requests that are traced
    untraced_p: float  # probability that a sample has no tracing at all


STANDARD = Dist(n_base=(50, 110), n_recent=(10, 22), jitter=(0.1, 0.35), outlier_p=0.01, base_err=(0.0, 0.03),
                decoy_p=0.25, drop=(0.0, 0.1), severity=(0.35, 1.0), exc_p=(0.6, 1.0), timeout_log_p=(0.6, 1.0),
                slow_extra=(500, 2500), surge_mult=(3.0, 6.0), trace_p=(0.7, 1.0), untraced_p=0.15)
SHIFTED = Dist(n_base=(25, 60), n_recent=(7, 14), jitter=(0.3, 0.7), outlier_p=0.04, base_err=(0.0, 0.06),
               decoy_p=0.45, drop=(0.05, 0.3), severity=(0.25, 0.9), exc_p=(0.4, 1.0), timeout_log_p=(0.3, 1.0),
               slow_extra=(350, 1800), surge_mult=(2.5, 5.0), trace_p=(0.3, 0.9), untraced_p=0.3)
DISTS = {"standard": STANDARD, "shifted": SHIFTED}


@dataclass
class Sample:
    events: list[dict]
    label: str  # one of CLASSES, or "none" for healthy traffic
    params: dict = field(default_factory=dict)


def _line(t: datetime, route: str, status: int, duration: float, version: str, rid: str, message: str = "request", **extra) -> dict:
    return {"event_time": t.isoformat(), "service_name": "shop-web", "environment": "production",
            "level": "error" if status >= 500 else "info", "version": version, "message": message,
            "request_id": rid, "route": route, "method": "POST", "status": status,
            "duration_ms": round(max(0.5, duration), 1), **extra}


def _trace(t: datetime, route: str, status: int, duration: float, rid: str, children: list, cpu_ms: float) -> list[dict]:
    """Span events for one request: a root span with cpu_ms plus children laid end to end."""
    tid = hashlib.sha256(f"trace|{rid}".encode()).hexdigest()[:32]
    start = int(t.timestamp() * 1_000_000) * 1000
    root = tid[:16]
    out = [{"_span": {"traceId": tid, "spanId": root, "name": f"POST {route}", "serviceName": "shop-web",
                      "startTimeUnixNano": start, "endTimeUnixNano": start + int(max(0.5, duration) * 1e6),
                      "status": {"code": 2 if status >= 500 else 1},
                      "attributes": {"http.route": route, "cpu_ms": round(cpu_ms, 1)}}}]
    at = start
    for j, (name, ms, failed) in enumerate(children):
        out.append({"_span": {"traceId": tid, "spanId": f"{tid[16:28]}{j + 1:04x}", "parentSpanId": root, "name": name,
                              "serviceName": "shop-web", "startTimeUnixNano": at, "endTimeUnixNano": at + int(max(0.1, ms) * 1e6),
                              "status": {"code": 2 if failed else 1}}})
        at += int(max(0.1, ms) * 1e6)
    return out


def _healthy_children(r: random.Random, route: str, dur: float) -> list:
    if route == "/api/checkout":
        return [("db.pool.acquire", r.uniform(0.2, 2), False), ("db.query orders.lookup", dur * r.uniform(0.2, 0.4), False),
                ("payment.authorize", dur * r.uniform(0.1, 0.25), False), ("db.pool.acquire", r.uniform(0.2, 2), False),
                ("db.query orders.insert", dur * r.uniform(0.2, 0.35), False)]
    if route == "/api/products":
        return [("cache.get catalogue", r.uniform(0.2, 1.5), False)]
    return []


def generate(label: str, seed: int, dist: Dist = STANDARD) -> Sample:
    r = random.Random(f"{label}-{seed}-{dist.n_base}")
    u = lambda lo_hi: r.uniform(*lo_hi)
    mu = {"/api/checkout": r.choice([r.uniform(15, 60), r.uniform(200, 650)]),  # local DB vs remote DB
          "/api/products": r.uniform(5, 40), "/api/cart": r.uniform(4, 25)}
    jitter, base_err, drop = u(dist.jitter), u(dist.base_err), u(dist.drop)
    decoy = label != "release_regression" and r.random() < dist.decoy_p
    severity, exc_p, tlog_p = u(dist.severity), u(dist.exc_p), u(dist.timeout_log_p)
    slow_extra, surge = u(dist.slow_extra), u(dist.surge_mult)
    timeout_ms = r.uniform(2000, 5000)
    slow_products_too = label == "slow_dependency" and r.random() < 0.3
    # Tracing coverage varies: some systems trace nothing, others only a share of requests.
    traced_sample = r.random() >= dist.untraced_p
    trace_p = u(dist.trace_p)
    cache_timeout = r.uniform(150, 400)
    fail_p, fail_ms = r.uniform(0.6, 0.85), r.uniform(250, 500)
    # Closed-loop clients (scripts, bots, users waiting on a page) send the next request only after
    # the previous one returns, so slow responses also LOWER the request rate. Observed on the real
    # shop under the S03 slow-query fault; about half of the simulated traffic behaves this way.
    closed_loop = r.random() < 0.5

    def healthy_duration(route: str) -> float:
        d = mu[route] * math.exp(r.gauss(0, jitter))
        return d * r.uniform(5, 10) if r.random() < dist.outlier_p else d  # cold-start outliers

    def work_ms(dur: float) -> float:  # on-CPU time of a request that is mostly waiting on I/O
        return min(dur, r.uniform(1, 6) + dur * r.uniform(0.02, 0.08))

    events: list[dict] = []
    k = 0

    def emit(e: dict) -> None:
        if r.random() >= drop:  # missing telemetry
            events.append(e)

    def emit_request(ts, route, status, dur, version, rid, message="request", children=None, cpu_ms=None, **extra):
        traced = traced_sample and r.random() < trace_p
        if traced:  # as in the shop, a traced request's log line carries its trace id
            extra["trace_id"] = hashlib.sha256(f"trace|{rid}".encode()).hexdigest()[:32]
        emit(_line(ts, route, status, dur, version, rid, message, **extra))
        if traced:
            kids = _healthy_children(r, route, dur) if children is None else children
            for sp in _trace(ts, route, status, dur, rid, kids, work_ms(dur) if cpu_ms is None else cpu_ms):
                emit(sp)

    # Healthy baseline, ending before the 120 s detection window.
    n_base = r.randint(*dist.n_base)
    for i in range(n_base):
        t = NOW - timedelta(seconds=600 - i * (460 / n_base))
        for route in mu:
            k += 1
            err = r.random() < base_err
            emit_request(t + timedelta(milliseconds=r.uniform(0, 900)), route, 500 if err else 200,
                         healthy_duration(route), "v1", f"b{k}")

    # Incident window.
    n_recent = r.randint(*dist.n_recent)
    if label == "traffic_surge":
        n_recent = int(n_recent * surge)
    added_ms = {"slow_dependency": slow_extra, "payment_provider_timeout": timeout_ms, "db_pool_exhaustion": slow_extra,
                "cache_unavailable": 2 * cache_timeout, "resource_saturation": slow_extra * 0.5,
                "retry_storm": fail_ms * 2.5}.get(label, 0.0) * severity
    if closed_loop and added_ms:
        cycle_ms = r.uniform(300, 1500)  # a client's usual time per round of requests
        n_recent = max(5, int(n_recent * cycle_ms / (cycle_ms + added_ms)))
    version = "v2" if (label == "release_regression" or decoy) else "v1"
    for i in range(n_recent):
        t = NOW - timedelta(seconds=105 - i * (100 / n_recent))
        for route in mu:
            k += 1
            rid = f"r{k}"
            ts = t + timedelta(milliseconds=r.uniform(0, 900))
            dur = healthy_duration(route)
            status, message, extra, kids, cpu = (500 if r.random() < base_err else 200), "request", {}, None, None
            affected = route == "/api/checkout" and r.random() < severity
            if label == "release_regression" and affected:
                status, dur, kids = 500, r.uniform(0.5, 30), []  # throws before touching anything
                if r.random() < exc_p:
                    message, extra = "unhandled_exception", {"error": "TypeError: cannot read properties of undefined"}
            elif label == "payment_provider_timeout" and affected:
                status, dur = 504, timeout_ms * r.uniform(0.98, 1.03)
                kids = [("db.pool.acquire", r.uniform(0.2, 2), False), ("db.query orders.lookup", r.uniform(2, 20), False),
                        ("payment.authorize", timeout_ms, True)]
                if r.random() < tlog_p:
                    emit(_line(ts + timedelta(milliseconds=5), route, 504, dur, version, rid, "payment_timeout",
                               error=f"payment provider timed out after {int(timeout_ms)}ms"))
            elif label == "slow_dependency" and (affected or (slow_products_too and route == "/api/products" and r.random() < severity)):
                extra_ms = slow_extra * r.uniform(0.7, 1.3)
                kids = _healthy_children(r, route, dur)
                kids = ([("db.query catalogue", extra_ms, False)] if route == "/api/products"
                        else [kids[0], (kids[1][0], kids[1][1] + extra_ms, False), *kids[2:]])
                dur += extra_ms
            elif label == "db_pool_exhaustion" and affected:
                wait = slow_extra * r.uniform(0.35, 0.65)  # each of the two queries waits for a connection
                kids = _healthy_children(r, route, dur)
                kids = [("db.pool.acquire", wait, False), kids[1], kids[2], ("db.pool.acquire", wait, False), kids[4]]
                dur += 2 * wait
            elif label == "cache_unavailable" and route == "/api/products" and r.random() < severity:
                kids = [("cache.get catalogue", cache_timeout, True), ("cache.set catalogue", cache_timeout, True)]
                dur += 2 * cache_timeout
            elif label == "resource_saturation" and r.random() < severity:  # every route burns CPU
                burn = slow_extra * r.uniform(0.3, 0.7)
                dur += burn
                cpu = burn + work_ms(dur - burn)
                kids = _healthy_children(r, route, dur - burn)
            elif label == "retry_storm" and affected:
                kids = [("db.pool.acquire", r.uniform(0.2, 2), False), ("db.query orders.lookup", r.uniform(2, 20), False)]
                ok = False
                for attempt in range(1, 6):
                    if r.random() < fail_p:
                        kids.append(("payment.authorize", fail_ms * r.uniform(0.9, 1.1), True))
                        if attempt < 5 and r.random() < tlog_p:
                            emit(_line(ts + timedelta(milliseconds=fail_ms * attempt), route, 0, 0, version, rid, "payment_retry",
                                       attempt=attempt, error="payment provider returned 503 (transient)") | {"level": "warning"})
                    else:
                        kids.append(("payment.authorize", r.uniform(2, 8), False))
                        ok = True
                        break
                if ok:
                    kids += [("db.pool.acquire", r.uniform(0.2, 2), False), ("db.query orders.insert", r.uniform(2, 20), False)]
                status = 200 if ok else 502
                dur = sum(c[1] for c in kids) + r.uniform(3, 12)
            elif label == "traffic_surge":
                dur *= r.uniform(1.5, 3.5)  # overload slows everything a bit
                cpu = dur * r.uniform(0.15, 0.45)  # and contends for CPU
                if r.random() < 0.08 * severity:
                    status = 503
            elif label == "unknown" and affected:
                status, dur, kids = 500, r.uniform(20, 80), []  # plain errors with no distinguishing signal
            emit_request(ts, route, status, dur, version, rid, message, kids, cpu, **extra)

    params = {"closed_loop": closed_loop, "jitter": jitter, "base_err": base_err, "drop": drop, "decoy": decoy, "severity": severity,
              "exc_p": exc_p, "timeout_log_p": tlog_p, "checkout_mu": mu["/api/checkout"], "n_base": n_base,
              "n_recent": n_recent, "traced": traced_sample, "trace_p": trace_p}
    return Sample(events, label, params)
