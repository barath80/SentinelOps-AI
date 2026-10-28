"""Seeded fault scenarios with hidden ground truth.

A scenario produces (1) the telemetry every system sees, (2) the telemetry that would follow a
given recovery action (a simple world model: a fault stops only if the action that fixes it is
the one executed), and (3) the ground truth, which is NEVER passed to a system.

Telemetry has the shape the real shop emits: one log line per request plus a trace (a root span
with `cpu_ms` and child spans for the connection pool, queries, the payment provider and the
cache). Span events are marked with a `_span` key; everything else is a `shop_json` log line.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
VERIFY_WINDOW_S = 60

# Which executed action stops which fault mode. plain500 has no known fix.
FIXERS = {"exception": "rollback_release", "timeout": "restore_payment_simulator",
          "slow": "apply_query_fix", "products_slow": "apply_query_fix", "plain500": None,
          "pool": "recycle_db_pool", "cache_down": "restore_cache", "cpu": "scale_out",
          "retry": "enable_retry_backoff",
          # Faults none of the catalogued actions fixes (the apparent cause is a decoy):
          "exception_mixed": None, "timeout_unrelated": None}


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    checkout_mode: str  # healthy | exception | timeout | slow | plain500 | pool | retry | cpu | ...
    products_mode: str  # healthy | products_slow | cache_down | cpu
    version_after: str  # release label on recent traffic while the fault is active
    truth_causes: frozenset  # causes that really explain the incident (empty: not determinable)
    safe_actions: frozenset  # actions that are correct for this scenario
    description: str
    # True for scenarios written specifically to exercise the falsification mechanism: a plausible
    # leader that a direct test can disprove. Reported separately so results are not oversold.
    falsification_probe: bool = False
    # Telemetry faults: the service is healthy but its data is wrong (S11: clock running ahead).
    clock_ahead_s: int = 0

    @property
    def has_fault(self) -> bool:
        return self.checkout_mode != "healthy" or self.products_mode != "healthy"

    @property
    def ambiguous(self) -> bool:
        return self.has_fault and not self.truth_causes

    @property
    def telemetry_fault(self) -> bool:
        return self.clock_ahead_s > 0


F = frozenset
SCENARIOS: list[Scenario] = [
    Scenario("S00", "Healthy traffic", "healthy", "healthy", "v1", F(), F(), "No fault: nothing should be reported."),
    Scenario("S01", "Bad checkout deployment", "exception", "healthy", "v2", F({"release_regression"}),
             F({"rollback_release"}), "New release throws on checkout; other routes fine."),
    Scenario("S02", "Database connection-pool exhaustion", "pool", "healthy", "v1", F({"db_pool_exhaustion"}),
             F({"recycle_db_pool"}), "Checkout waits for a database connection; the queries themselves stay fast."),
    Scenario("S03", "Slow database query", "slow", "healthy", "v1", F({"slow_dependency"}),
             F({"apply_query_fix"}), "Checkout is slow but succeeds."),
    Scenario("S04", "Cache unavailable", "healthy", "cache_down", "v1", F({"cache_unavailable"}),
             F({"restore_cache"}), "Catalogue reads time out against the cache and fall back to the origin."),
    Scenario("S05", "Payment provider timeout", "timeout", "healthy", "v1", F({"payment_provider_timeout"}),
             F({"restore_payment_simulator"}), "Checkout 504s after ~3 s; timeouts are logged."),
    Scenario("S06", "CPU saturation", "cpu", "cpu", "v1", F({"resource_saturation"}),
             F({"scale_out"}), "Every route is slow because requests spend their time on-CPU."),
    Scenario("S07", "Retry storm", "retry", "healthy", "v1", F({"retry_storm"}),
             F({"enable_retry_backoff"}), "A flaky provider plus immediate retries: several provider calls per checkout."),
    Scenario("S08", "Unexplained errors (ambiguous)", "plain500", "healthy", "v1", F(), F(),
             "Checkout errors with no release change, no exceptions, no timeouts: not determinable."),
    Scenario("S09", "Misleading deployment correlation", "timeout", "healthy", "v2", F({"payment_provider_timeout"}),
             F({"restore_payment_simulator"}), "Release label changed, but the failures are payment timeouts."),
    Scenario("S10", "Two simultaneous faults", "exception", "products_slow", "v2",
             F({"release_regression", "slow_dependency"}), F({"rollback_release", "apply_query_fix"}),
             "Checkout throws on the new release AND the products route is slow for a different reason."),
    Scenario("S11", "Clock running ahead", "healthy", "healthy", "v1", F(), F(),
             "Healthy service whose recent telemetry is stamped 4 minutes in the future.", clock_ahead_s=240),
    Scenario("P1", "Probe: both releases fail", "exception_mixed", "healthy", "v2", F(), F(),
             "Exceptions on the old AND new release while the label changes: rolling back cannot help.",
             falsification_probe=True),
    Scenario("P2", "Probe: unrelated payment timeouts", "timeout_unrelated", "healthy", "v1", F(), F(),
             "Payment timeouts are logged, but not by the requests that are failing.",
             falsification_probe=True),
]
BY_ID = {s.id: s for s in SCENARIOS}


def _line(t: datetime, route: str, status: int, duration: float, version: str, message: str = "request",
          request_id: str = "", **extra) -> dict:
    return {"event_time": t.isoformat(), "service_name": "shop-web", "environment": "production",
            "level": "error" if status >= 500 else "info", "version": version, "message": message,
            "request_id": request_id, "route": route, "method": "POST", "status": status,
            "duration_ms": round(duration, 1), **extra}


def _ns(t: datetime) -> int:
    return int(t.timestamp() * 1_000_000) * 1000


def _request(t: datetime, route: str, status: int, duration: float, version: str, rid: str, message: str = "request",
             children: tuple = (), cpu_share: float | None = None, traced: bool = True, **extra) -> list[dict]:
    """A request's log line plus its trace: children are (name, ms, failed) laid end to end.
    cpu_ms is a few ms of real work unless `cpu_share` says the request is CPU-bound: waiting on a
    pool, a query or a provider does not use CPU (process.cpuUsage() in the shop agrees)."""
    tid = hashlib.sha256(f"trace|{rid}".encode()).hexdigest()[:32]
    out = [_line(t, route, status, duration, version, message, rid, trace_id=tid, **extra)]
    if not traced:
        return out
    root = tid[:16]
    start = _ns(t)
    out.append({"_span": {"traceId": tid, "spanId": root, "name": f"POST {route}", "serviceName": "shop-web",
                          "startTimeUnixNano": start, "endTimeUnixNano": start + int(duration * 1e6),
                          "status": {"code": 2 if status >= 500 else 1},
                          "attributes": {"http.route": route,
                                         "cpu_ms": round(duration * cpu_share if cpu_share else 1 + min(duration, 30) * 0.1, 1)}}})
    at = start
    for j, (name, ms, failed) in enumerate(children):
        out.append({"_span": {"traceId": tid, "spanId": f"{tid[16:28]}{j + 1:04x}", "parentSpanId": root, "name": name,
                              "serviceName": "shop-web", "startTimeUnixNano": at, "endTimeUnixNano": at + int(ms * 1e6),
                              "status": {"code": 2 if failed else 1}}})
        at += int(ms * 1e6)
    return out


def _healthy_checkout_children(rng: random.Random) -> tuple:
    return (("db.pool.acquire", 0.5, False), ("db.query orders.lookup", 3 + rng.random() * 3, False),
            ("payment.authorize", 3 + rng.random() * 2, False), ("db.pool.acquire", 0.5, False),
            ("db.query orders.insert", 3 + rng.random() * 3, False))


def _checkout(rng: random.Random, t: datetime, mode: str, version: str, rid: str, traced: bool = True) -> list[dict]:
    r = lambda *a, **k: _request(t, "/api/checkout", *a, traced=traced, **k)
    if mode == "healthy":
        return r(201, 18 + rng.random() * 10, "v1", rid, children=_healthy_checkout_children(rng))
    if mode in ("exception", "exception_mixed"):  # throws before touching the database
        return r(500, rng.random() * 3, version, rid, "unhandled_exception", error="TypeError: cannot read properties of undefined")
    if mode == "timeout":
        return (r(504, 2990 + rng.random() * 40, version, rid,
                  children=(("db.pool.acquire", 0.5, False), ("db.query orders.lookup", 4, False), ("payment.authorize", 3000, True)))
                + [_line(t + timedelta(milliseconds=5), "/api/checkout", 504, 3000, version, "payment_timeout", rid,
                         error="payment provider timed out after 3000ms")])
    if mode == "timeout_unrelated":
        # the failing request is a plain 504; the logged timeout belongs to a different request id
        return (r(504, 2990 + rng.random() * 40, version, rid)
                + [_line(t + timedelta(milliseconds=5), "/api/checkout", 504, 3000, version, "payment_timeout",
                         "other-" + rid, error="payment provider timed out after 3000ms")])
    if mode == "slow":
        dur = 1200 + rng.random() * 600
        return r(201, dur, version, rid, children=(("db.pool.acquire", 0.5, False), ("db.query orders.lookup", dur - 15, False),
                                                    ("payment.authorize", 4, False), ("db.pool.acquire", 0.5, False),
                                                    ("db.query orders.insert", 5, False)))
    if mode == "plain500":
        return r(500, 25 + rng.random() * 35, version, rid)
    if mode == "pool":  # each of the two queries waits out the acquire timeout
        wait = 1300 + rng.random() * 30
        return r(201, 2 * wait + 20, version, rid, children=(("db.pool.acquire", wait, False), ("db.query orders.lookup", 4, False),
                                                             ("payment.authorize", 4, False), ("db.pool.acquire", wait, False),
                                                             ("db.query orders.insert", 4, False)))
    if mode == "retry":
        kids, retries, ok = [("db.pool.acquire", 0.5, False), ("db.query orders.lookup", 4, False)], [], False
        for attempt in range(1, 6):
            if rng.random() < 0.75:
                kids.append(("payment.authorize", 400 + rng.random() * 10, True))
                if attempt < 5:
                    retries.append(_line(t + timedelta(milliseconds=410 * attempt), "/api/checkout", 0, 0, version,
                                         "payment_retry", rid, attempt=attempt, error="payment provider returned 503 (transient)")
                                   | {"level": "warning"})
            else:
                kids.append(("payment.authorize", 4, False))
                ok = True
                break
        if ok:
            kids += [("db.pool.acquire", 0.5, False), ("db.query orders.insert", 4, False)]
        dur = sum(k[1] for k in kids) + 8
        return r(201 if ok else 502, dur, version, rid, children=tuple(kids)) + retries
    if mode == "cpu":
        return r(201, 720 + rng.random() * 40, version, rid, children=_healthy_checkout_children(rng), cpu_share=0.95)
    raise ValueError(mode)


def _products(rng: random.Random, t: datetime, mode: str, rid: str, version: str = "v1", traced: bool = True) -> list[dict]:
    # The release label is app-wide (as in the real shop), so it is shared across routes.
    if mode == "products_slow":
        dur = 1100 + rng.random() * 500
        kids, share = (("db.query catalogue", dur - 10, False),), None
    elif mode == "cache_down":
        dur = 510 + rng.random() * 30
        kids, share = (("cache.get catalogue", 250, True), ("cache.set catalogue", 250, True)), None
    elif mode == "cpu":
        dur = 710 + rng.random() * 40
        kids, share = (("cache.get catalogue", 0.5, False),), 0.95
    else:
        dur = 8 + rng.random() * 4
        kids, share = (("cache.get catalogue", 0.5, False),), None
    return _request(t, "/api/products", 200, dur, version, rid, children=kids, cpu_share=share, traced=traced)


def _version(mode: str, i: int, base: str) -> str:
    return ("v2" if i % 2 else "v1") if mode == "exception_mixed" else base


def _cart(rng: random.Random, t: datetime, rid: str, version: str = "v1", cpu: bool = False, traced: bool = True) -> list[dict]:
    dur = 705 + rng.random() * 30 if cpu else 5 + rng.random() * 4
    return _request(t, "/api/cart", 200, dur, version, rid, cpu_share=0.95 if cpu else None, traced=traced)


def _shift(events: list[dict], seconds: int) -> list[dict]:
    """Stamp events `seconds` later than they happened (a clock running ahead)."""
    if not seconds:
        return events
    out = []
    for e in events:
        if "_span" in e:
            sp = dict(e["_span"])
            sp["startTimeUnixNano"] += seconds * 1_000_000_000
            sp["endTimeUnixNano"] += seconds * 1_000_000_000
            out.append({"_span": sp})
        else:
            out.append(e | {"event_time": (datetime.fromisoformat(e["event_time"]) + timedelta(seconds=seconds)).isoformat()})
    return out


def make_events(s: Scenario, seed: int) -> list[dict]:
    """The telemetry all systems receive: healthy baseline, then the fault in the last ~100 s."""
    rng = random.Random(f"{s.id}-{seed}")
    out: list[dict] = []
    n_base = rng.randint(55, 80)
    for i in range(n_base):
        t = NOW - timedelta(seconds=600 - i * (470 / n_base))
        out += _checkout(rng, t, "healthy", "v1", f"b{i}c")
        out += _products(rng, t + timedelta(seconds=1), "healthy", f"b{i}p")
        out += _cart(rng, t + timedelta(seconds=2), f"b{i}k")
    n_recent = rng.randint(9, 16)
    for i in range(n_recent):
        t = NOW - timedelta(seconds=100 - i * (92 / n_recent))
        ver = _version(s.checkout_mode, i, s.version_after)
        cpu = s.checkout_mode == "cpu"
        batch = (_checkout(rng, t, s.checkout_mode, ver, f"r{i}c")
                 + _products(rng, t + timedelta(seconds=1), s.products_mode, f"r{i}p", ver)
                 + _cart(rng, t + timedelta(seconds=2), f"r{i}k", ver, cpu=cpu))  # the cart is only ever slowed by CPU
        out += _shift(batch, s.clock_ahead_s)
    return out


def post_action_modes(s: Scenario, action: str | None) -> tuple[str, str, str]:
    """Checkout mode, products mode and release label after `action` is executed."""
    fixed = lambda mode: "healthy" if (action is not None and FIXERS.get(mode) == action) else mode
    version = "v1" if action == "rollback_release" else s.version_after
    return fixed(s.checkout_mode), fixed(s.products_mode), version


def truly_recovered(s: Scenario, action: str | None) -> bool:
    c, p, _ = post_action_modes(s, action)
    return c == "healthy" and p == "healthy"


def make_post_action_events(s: Scenario, seed: int, action: str | None) -> list[dict]:
    """Telemetry for the verification window that starts just after the action ends (logs only:
    verification is measured from request SLIs)."""
    rng = random.Random(f"{s.id}-{seed}-post-{action}")
    c_mode, p_mode, version = post_action_modes(s, action)
    start = NOW + timedelta(seconds=5)
    out: list[dict] = []
    for i in range(45):
        t = start + timedelta(seconds=1 + i * 1.3 + rng.random() * 0.2)
        ver = _version(c_mode, i, version)
        if c_mode == "exception_mixed" and action == "rollback_release":
            ver = "v1"  # the rollback removes the new release, but the old one keeps failing
        out += _checkout(rng, t, c_mode, ver, f"a{i}c", traced=False)
        out += _products(rng, t + timedelta(milliseconds=300), p_mode, f"a{i}p", ver, traced=False)
        out += _cart(rng, t + timedelta(milliseconds=600), f"a{i}k", ver, cpu=c_mode == "cpu", traced=False)
    return out


def window() -> tuple[datetime, datetime]:
    start = NOW + timedelta(seconds=5)
    return start, start + timedelta(seconds=VERIFY_WINDOW_S)
