"""Seeded fault scenarios with hidden ground truth.

A scenario produces (1) the telemetry every system sees, (2) the telemetry that would follow a
given recovery action (a simple world model: a fault stops only if the action that fixes it is
the one executed), and (3) the ground truth, which is NEVER passed to a system.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
VERIFY_WINDOW_S = 60

# Which executed action stops which fault mode. plain500 has no known fix.
FIXERS = {"exception": "rollback_release", "timeout": "restore_payment_simulator",
          "slow": "apply_query_fix", "products_slow": "apply_query_fix", "plain500": None,
          # Faults none of the catalogued actions fixes (the apparent cause is a decoy):
          "exception_mixed": None, "timeout_unrelated": None}


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    checkout_mode: str  # healthy | exception | timeout | slow | plain500
    products_mode: str  # healthy | products_slow
    version_after: str  # release label on recent traffic while the fault is active
    truth_causes: frozenset  # causes that really explain the incident (empty: not determinable)
    safe_actions: frozenset  # actions that are correct for this scenario
    description: str
    # True for scenarios written specifically to exercise the falsification mechanism: a plausible
    # leader that a direct test can disprove. Reported separately so results are not oversold.
    falsification_probe: bool = False

    @property
    def has_fault(self) -> bool:
        return self.checkout_mode != "healthy" or self.products_mode != "healthy"

    @property
    def ambiguous(self) -> bool:
        return self.has_fault and not self.truth_causes


F = frozenset
SCENARIOS: list[Scenario] = [
    Scenario("S00", "Healthy traffic", "healthy", "healthy", "v1", F(), F(), "No fault: nothing should be reported."),
    Scenario("S01", "Bad checkout deployment", "exception", "healthy", "v2", F({"release_regression"}),
             F({"rollback_release"}), "New release throws on checkout; other routes fine."),
    Scenario("S03", "Slow database query", "slow", "healthy", "v1", F({"slow_dependency"}),
             F({"apply_query_fix"}), "Checkout is slow but succeeds."),
    Scenario("S05", "Payment provider timeout", "timeout", "healthy", "v1", F({"payment_provider_timeout"}),
             F({"restore_payment_simulator"}), "Checkout 504s after ~3 s; timeouts are logged."),
    Scenario("S08", "Unexplained errors (ambiguous)", "plain500", "healthy", "v1", F(), F(),
             "Checkout errors with no release change, no exceptions, no timeouts: not determinable."),
    Scenario("S09", "Misleading deployment correlation", "timeout", "healthy", "v2", F({"payment_provider_timeout"}),
             F({"restore_payment_simulator"}), "Release label changed, but the failures are payment timeouts."),
    Scenario("S10", "Two simultaneous faults", "exception", "products_slow", "v2",
             F({"release_regression", "slow_dependency"}), F({"rollback_release", "apply_query_fix"}),
             "Checkout throws on the new release AND the products route is slow for a different reason."),
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


def _checkout(rng: random.Random, t: datetime, mode: str, version: str, rid: str) -> list[dict]:
    if mode == "healthy":
        return [_line(t, "/api/checkout", 201, 18 + rng.random() * 10, "v1", request_id=rid)]
    if mode == "exception":
        return [_line(t, "/api/checkout", 500, rng.random() * 3, version, "unhandled_exception", rid,
                      error="TypeError: cannot read properties of undefined")]
    if mode == "timeout":
        return [_line(t, "/api/checkout", 504, 2990 + rng.random() * 40, version, request_id=rid),
                _line(t + timedelta(milliseconds=5), "/api/checkout", 504, 3000, version, "payment_timeout", rid,
                      error="payment provider timed out after 3000ms")]
    if mode == "slow":
        return [_line(t, "/api/checkout", 201, 1200 + rng.random() * 600, version, request_id=rid)]
    if mode == "plain500":
        return [_line(t, "/api/checkout", 500, 25 + rng.random() * 35, version, request_id=rid)]
    if mode == "exception_mixed":
        return [_line(t, "/api/checkout", 500, rng.random() * 3, version, "unhandled_exception", rid,
                      error="TypeError: cannot read properties of undefined")]
    if mode == "timeout_unrelated":
        # the failing request is a plain 504; the logged timeout belongs to a different request id
        return [_line(t, "/api/checkout", 504, 2990 + rng.random() * 40, version, request_id=rid),
                _line(t + timedelta(milliseconds=5), "/api/checkout", 504, 3000, version, "payment_timeout",
                      "other-" + rid, error="payment provider timed out after 3000ms")]
    raise ValueError(mode)


def _products(rng: random.Random, t: datetime, mode: str, rid: str, version: str = "v1") -> dict:
    # The release label is app-wide (as in the real shop), so it is shared across routes.
    dur = 1100 + rng.random() * 500 if mode == "products_slow" else 8 + rng.random() * 4
    return _line(t, "/api/products", 200, dur, version, request_id=rid)


def _version(mode: str, i: int, base: str) -> str:
    return ("v2" if i % 2 else "v1") if mode == "exception_mixed" else base


def _cart(rng: random.Random, t: datetime, rid: str, version: str = "v1") -> dict:
    return _line(t, "/api/cart", 200, 5 + rng.random() * 4, version, request_id=rid)


def make_events(s: Scenario, seed: int) -> list[dict]:
    """The telemetry all systems receive: healthy baseline, then the fault in the last ~100 s."""
    rng = random.Random(f"{s.id}-{seed}")
    out: list[dict] = []
    n_base = rng.randint(55, 80)
    for i in range(n_base):
        t = NOW - timedelta(seconds=600 - i * (470 / n_base))
        out += _checkout(rng, t, "healthy", "v1", f"b{i}c")
        out.append(_products(rng, t + timedelta(seconds=1), "healthy", f"b{i}p"))
        out.append(_cart(rng, t + timedelta(seconds=2), f"b{i}k"))
    n_recent = rng.randint(9, 16)
    for i in range(n_recent):
        t = NOW - timedelta(seconds=100 - i * (92 / n_recent))
        ver = _version(s.checkout_mode, i, s.version_after)
        out += _checkout(rng, t, s.checkout_mode, ver, f"r{i}c")
        out.append(_products(rng, t + timedelta(seconds=1), s.products_mode, f"r{i}p", ver))
        out.append(_cart(rng, t + timedelta(seconds=2), f"r{i}k", ver))  # the cart route is never faulty
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
    """Telemetry for the verification window that starts just after the action ends."""
    rng = random.Random(f"{s.id}-{seed}-post-{action}")
    c_mode, p_mode, version = post_action_modes(s, action)
    start = NOW + timedelta(seconds=5)
    out: list[dict] = []
    for i in range(45):
        t = start + timedelta(seconds=1 + i * 1.3 + rng.random() * 0.2)
        ver = _version(c_mode, i, version)
        if c_mode == "exception_mixed" and action == "rollback_release":
            ver = "v1"  # the rollback removes the new release, but the old one keeps failing
        out += _checkout(rng, t, c_mode, ver, f"a{i}c")
        out.append(_products(rng, t + timedelta(milliseconds=300), p_mode, f"a{i}p", ver))
        out.append(_cart(rng, t + timedelta(milliseconds=600), f"a{i}k", ver))
    return out


def window() -> tuple[datetime, datetime]:
    start = NOW + timedelta(seconds=5)
    return start, start + timedelta(seconds=VERIFY_WINDOW_S)
