"""Action allow-list, blast-radius estimate, and the policy decision (default deny).

The LLM (or any caller) can only *name* an action template. Whether it may run is decided
here, by code: unknown actions, disallowed environments and disruptive actions with critical
dependents are refused. Nothing in telemetry or model output can change these rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field

POLICY_VERSION = "policy-v1"


@dataclass(frozen=True)
class ActionSpec:
    id: str
    description: str
    target_service: str
    risk: str  # low | medium | high (declared, conservative)
    environments: tuple[str, ...]  # where it may ever run; () means nowhere
    approval_required: bool
    disruptive: bool  # restarts / removes capacity, as opposed to restoring a known-good setting
    rollback_template: str | None = None


CATALOGUE: dict[str, ActionSpec] = {s.id: s for s in [
    ActionSpec("rollback_release", "Roll the shop back to the last known-good release", "shop-web",
               "medium", ("sandbox", "demo"), True, False),
    ActionSpec("restore_payment_simulator", "Set the payment simulator back to healthy mode", "payment-simulator",
               "low", ("sandbox", "demo"), True, False),
    ActionSpec("apply_query_fix", "Apply the indexed-query variant for the slow checkout query", "postgres",
               "medium", ("sandbox", "demo"), True, False),
    # Deliberately present but never allowed: demonstrates the policy block (scenario S12).
    ActionSpec("restart_shared_database", "Restart the shared PostgreSQL instance", "postgres",
               "high", (), True, True),
]}

# What each cause maps to. traffic_surge has no safe action yet, so nothing is recommended.
RECOMMENDED_ACTION = {
    "release_regression": "rollback_release",
    "payment_provider_timeout": "restore_payment_simulator",
    "slow_dependency": "apply_query_fix",
}

# service -> services it depends on; criticality of each service.
DEPENDS_ON = {"shop-web": ["postgres", "payment-simulator"], "postgres": [], "payment-simulator": []}
CRITICALITY = {"shop-web": "critical", "postgres": "critical", "payment-simulator": "high"}


def dependents(service: str) -> list[str]:
    """Services that (transitively) depend on `service`: what a failure of it can reach."""
    found: list[str] = []
    changed = True
    while changed:
        changed = False
        for svc, deps in DEPENDS_ON.items():
            if svc not in found and svc != service and (service in deps or any(d in found for d in deps)):
                found.append(svc)
                changed = True
    return sorted(found)


@dataclass
class PolicyDecision:
    allowed: bool
    approval_required: bool
    reasons: list[str] = field(default_factory=list)
    blast_radius: dict = field(default_factory=dict)


def blast_radius(spec: ActionSpec) -> dict:
    deps = dependents(spec.target_service)
    critical = [d for d in deps if CRITICALITY.get(d) == "critical"]
    label = "high" if (spec.disruptive and critical) else ("medium" if deps or spec.risk != "low" else "low")
    return {
        "target": spec.target_service,
        "dependents": deps,
        "critical_dependents": critical,
        "disruptive": spec.disruptive,
        "risk_label": label,
        "note": "Deterministic reachability over a static topology. A conservative label, not a probability.",
    }


def evaluate(action_id: str, environment: str) -> PolicyDecision:
    spec = CATALOGUE.get(action_id)
    if spec is None:
        return PolicyDecision(False, True, ["unknown_action: not on the allow-list"])
    radius = blast_radius(spec)
    reasons: list[str] = []
    if environment not in spec.environments:
        reasons.append(f"environment_not_permitted: {action_id} may not run in '{environment}'")
    if spec.disruptive and radius["critical_dependents"]:
        reasons.append("blast_radius: disruptive action reaches critical dependents " + ", ".join(radius["critical_dependents"]))
    approval = spec.approval_required or spec.risk != "low" or radius["risk_label"] != "low"
    return PolicyDecision(not reasons, approval, reasons, radius)
