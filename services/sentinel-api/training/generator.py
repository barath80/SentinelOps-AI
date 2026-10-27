"""Parametric incident generator for training the root-cause classifier.

Unlike the benchmark (a few fixed fault shapes), every sample here draws its own traffic level,
latencies, noise, cold-start outliers, missing logs, partial severity and decoy deployments, so
the classes overlap the way real incidents do. Two distributions are provided:

  standard  the training distribution
  shifted   harder and different: sparser traffic, more noise, more decoys, more missing logs,
            weaker signals. Used only for testing, to measure robustness to distribution shift.

The label is returned separately and is never part of the telemetry.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
CLASSES = ["release_regression", "payment_provider_timeout", "slow_dependency", "traffic_surge", "unknown"]


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


STANDARD = Dist(n_base=(50, 110), n_recent=(10, 22), jitter=(0.1, 0.35), outlier_p=0.01, base_err=(0.0, 0.03),
                decoy_p=0.25, drop=(0.0, 0.1), severity=(0.35, 1.0), exc_p=(0.6, 1.0), timeout_log_p=(0.6, 1.0),
                slow_extra=(500, 2500), surge_mult=(3.0, 6.0))
SHIFTED = Dist(n_base=(25, 60), n_recent=(7, 14), jitter=(0.3, 0.7), outlier_p=0.04, base_err=(0.0, 0.06),
               decoy_p=0.45, drop=(0.05, 0.3), severity=(0.25, 0.9), exc_p=(0.4, 1.0), timeout_log_p=(0.3, 1.0),
               slow_extra=(350, 1800), surge_mult=(2.5, 5.0))
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

    def healthy_duration(route: str) -> float:
        d = mu[route] * math.exp(r.gauss(0, jitter))
        return d * r.uniform(5, 10) if r.random() < dist.outlier_p else d  # cold-start outliers

    events: list[dict] = []
    k = 0

    def emit(e: dict) -> None:
        if r.random() >= drop:  # missing telemetry
            events.append(e)

    # Healthy baseline, ending before the 120 s detection window.
    n_base = r.randint(*dist.n_base)
    for i in range(n_base):
        t = NOW - timedelta(seconds=600 - i * (460 / n_base))
        for route in mu:
            k += 1
            err = r.random() < base_err
            emit(_line(t + timedelta(milliseconds=r.uniform(0, 900)), route, 500 if err else 200,
                       healthy_duration(route), "v1", f"b{k}"))

    # Incident window.
    n_recent = r.randint(*dist.n_recent)
    if label == "traffic_surge":
        n_recent = int(n_recent * surge)
    version = "v2" if (label == "release_regression" or decoy) else "v1"
    for i in range(n_recent):
        t = NOW - timedelta(seconds=105 - i * (100 / n_recent))
        for route in mu:
            k += 1
            rid = f"r{k}"
            ts = t + timedelta(milliseconds=r.uniform(0, 900))
            dur = healthy_duration(route)
            status, message, extra = (500 if r.random() < base_err else 200), "request", {}
            affected = route == "/api/checkout" and r.random() < severity
            if label == "release_regression" and affected:
                status, dur = 500, r.uniform(0.5, 30)
                if r.random() < exc_p:
                    message, extra = "unhandled_exception", {"error": "TypeError: cannot read properties of undefined"}
            elif label == "payment_provider_timeout" and affected:
                status, dur = 504, timeout_ms * r.uniform(0.98, 1.03)
                if r.random() < tlog_p:
                    emit(_line(ts + timedelta(milliseconds=5), route, 504, dur, version, rid, "payment_timeout",
                               error=f"payment provider timed out after {int(timeout_ms)}ms"))
            elif label == "slow_dependency" and (affected or (slow_products_too and route == "/api/products" and r.random() < severity)):
                dur += slow_extra * r.uniform(0.7, 1.3)
            elif label == "traffic_surge":
                dur *= r.uniform(1.5, 3.5)  # overload slows everything a bit
                if r.random() < 0.08 * severity:
                    status = 503
            elif label == "unknown" and affected:
                status, dur = 500, r.uniform(20, 80)  # plain errors with no distinguishing signal
            emit(_line(ts, route, status, dur, version, rid, message, **extra))

    params = {"jitter": jitter, "base_err": base_err, "drop": drop, "decoy": decoy, "severity": severity,
              "exc_p": exc_p, "timeout_log_p": tlog_p, "checkout_mu": mu["/api/checkout"], "n_base": n_base,
              "n_recent": n_recent}
    return Sample(events, label, params)
