"""Scoring against hidden ground truth, and aggregation with Wilson 95% intervals."""
from __future__ import annotations

import math
from collections import defaultdict

from .scenarios import Scenario, truly_recovered
from .systems import SystemResult


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def score_run(system: str, s: Scenario, seed: int, r: SystemResult) -> dict:
    determinable = bool(s.truth_causes)
    executed = r.action is not None
    recovered = truly_recovered(s, r.action) if executed else False
    return {
        "system": system, "scenario": s.id, "seed": seed, "has_fault": s.has_fault,
        "probe": s.falsification_probe,
        "determinable": determinable, "ambiguous": s.ambiguous,
        "detected": r.detected, "cause": r.cause, "action": r.action,
        "false_alarm": r.detected and not s.has_fault,
        "missed_detection": s.has_fault and not r.detected,
        "top1_correct": determinable and r.cause in s.truth_causes,
        "multi_cause": len(s.truth_causes) > 1,
        # a system that names a single cause cannot have found every cause of a multi-cause incident
        "complete_diagnosis": len(s.truth_causes) > 1 and r.cause is not None and {r.cause} >= s.truth_causes,
        "false_diagnosis": s.has_fault and r.cause is not None and r.cause not in s.truth_causes,
        "correct_abstention": s.ambiguous and r.detected and r.cause is None,
        "wrongful_abstention": determinable and r.detected and r.cause is None,
        "incorrect_intervention": executed and r.action not in s.safe_actions,
        "executed": executed, "truly_recovered": recovered,
        "claims_success": r.claims_success,
        "false_success": r.claims_success is True and not recovered,
        "verified_recovery": r.claims_success is True and recovered,
        "tests_run": r.tests_run, "elapsed_ms": r.elapsed_ms, "llm_tokens": r.llm_tokens,
        "verification": r.verification, "notes": r.notes,
    }


# (name, numerator key, denominator filter, description)
RATES = [
    ("detection_recall", lambda x: x["detected"], lambda x: x["has_fault"], "faults detected"),
    ("false_alarm_rate", lambda x: x["false_alarm"], lambda x: not x["has_fault"], "incidents raised on healthy traffic"),
    ("top1_accuracy", lambda x: x["top1_correct"], lambda x: x["determinable"], "correct cause named (determinable faults)"),
    ("complete_diagnosis_rate", lambda x: x["complete_diagnosis"], lambda x: x["multi_cause"], "all causes found (multi-cause faults)"),
    ("false_diagnosis_rate", lambda x: x["false_diagnosis"], lambda x: x["has_fault"], "a wrong cause named (all faults)"),
    ("correct_abstention_rate", lambda x: x["correct_abstention"], lambda x: x["ambiguous"], "abstained when not determinable"),
    ("wrongful_abstention_rate", lambda x: x["wrongful_abstention"], lambda x: x["determinable"], "abstained when a cause was determinable"),
    ("incorrect_intervention_rate", lambda x: x["incorrect_intervention"], lambda x: x["has_fault"], "wrong action proposed (all faults)"),
    ("false_success_rate", lambda x: x["false_success"], lambda x: x["executed"], "claimed recovery that did not happen (of executed actions)"),
    ("verified_recovery_rate", lambda x: x["verified_recovery"], lambda x: x["has_fault"], "recovery truly achieved and correctly claimed"),
]


def aggregate(rows: list[dict]) -> dict:
    by_system: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_system[r["system"]].append(r)
    out = {}
    for system, rs in by_system.items():
        rates = {}
        for name, num, den, desc in RATES:
            pool = [x for x in rs if den(x)]
            k = sum(1 for x in pool if num(x))
            lo, hi = wilson(k, len(pool))
            rates[name] = {"k": k, "n": len(pool), "rate": (k / len(pool)) if pool else None, "ci95": [lo, hi], "what": desc}
        out[system] = {
            "runs": len(rs), "rates": rates,
            "mean_tests_run": sum(x["tests_run"] for x in rs) / len(rs),
            "mean_elapsed_ms": sum(x["elapsed_ms"] for x in rs) / len(rs),
            "total_llm_tokens": sum(x["llm_tokens"] for x in rs),
        }
    return out


def per_scenario(rows: list[dict]) -> dict:
    cells: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        cells[(r["scenario"], r["system"])].append(r)
    out: dict = {}
    for (scn, system), rs in cells.items():
        causes: dict[str, int] = defaultdict(int)
        for x in rs:
            causes[x["cause"] or ("abstained" if x["detected"] else "not detected")] += 1
        out.setdefault(scn, {})[system] = {
            "n": len(rs), "answers": dict(causes),
            "incorrect_intervention": sum(x["incorrect_intervention"] for x in rs),
            "false_success": sum(x["false_success"] for x in rs),
            "verified_recovery": sum(x["verified_recovery"] for x in rs),
        }
    return out
