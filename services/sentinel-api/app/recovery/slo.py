"""SLI predicates and the verification evaluator.

Outcome comes ONLY from telemetry measured inside the verification window, never from the
fact that an action ran. Too few samples or a telemetry gap means "inconclusive", not "pass".
"""
from __future__ import annotations

import operator
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..analysis.detect import Sample, percentile

_OPS = {"<=": operator.le, "<": operator.lt}


class Predicate(BaseModel):
    sli: Literal["error_rate", "p95_latency_ms"]
    route: str
    op: Literal["<=", "<"] = "<="
    threshold: float
    min_samples: int = Field(default=5, ge=1)

    def describe(self) -> str:
        return f"{self.sli}({self.route}) {self.op} {self.threshold}"


def evaluate_predicate(p: Predicate, samples: list[Sample], start: datetime, end: datetime, max_gap_seconds: float) -> dict:
    mine = sorted((s for s in samples if s.route == p.route and start <= s.time <= end), key=lambda s: s.time)
    base = {"predicate": p.model_dump(), "description": p.describe(), "samples": len(mine)}
    if len(mine) < p.min_samples:
        return {**base, "status": "inconclusive", "reason": f"insufficient_samples: {len(mine)} < {p.min_samples}", "value": None}
    times = [start] + [s.time for s in mine] + [end]
    widest = max((b - a).total_seconds() for a, b in zip(times, times[1:]))
    if widest > max_gap_seconds:
        return {**base, "status": "inconclusive", "value": None,
                "reason": f"telemetry_gap: {widest:.0f}s without data (allowed {max_gap_seconds:.0f}s)"}
    if p.sli == "error_rate":
        value = sum(s.is_error for s in mine) / len(mine)
    else:
        value = percentile([s.duration_ms for s in mine], 95)
    met = _OPS[p.op](value, p.threshold)
    return {**base, "status": "met" if met else "unmet", "value": round(value, 4), "reason": ""}


def evaluate(success: list[Predicate], guardrails: list[Predicate], samples: list[Sample],
             start: datetime, end: datetime, max_gap_seconds: float) -> tuple[str, str, list[dict]]:
    """Returns (outcome, reason, details). outcome is pass | fail | inconclusive."""
    results = []
    for kind, preds in (("success", success), ("guardrail", guardrails)):
        for p in preds:
            results.append({"kind": kind, **evaluate_predicate(p, samples, start, end, max_gap_seconds)})
    unmet = [r for r in results if r["status"] == "unmet"]
    unknown = [r for r in results if r["status"] == "inconclusive"]
    breached = [r for r in unmet if r["kind"] == "guardrail"]
    if breached:
        return "fail", f"guardrail breached: {breached[0]['description']} (measured {breached[0]['value']})", results
    if unmet:  # one definite miss is enough to fail, even if other predicates are unknown
        return "fail", f"success condition not met: {unmet[0]['description']} (measured {unmet[0]['value']})", results
    if unknown:
        return "inconclusive", "; ".join(f"{r['description']}: {r['reason']}" for r in unknown), results
    return "pass", "all success conditions and guardrails held for the full verification window", results
