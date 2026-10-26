"""Recovery contracts: creation, approval, execution and verification, as a guarded state machine.

Invariants enforced here (and tested):
  * default deny: the policy engine must allow the action before a contract can proceed
  * every state change is an atomic compare-and-set and appends an immutable audit row
  * the proposer cannot approve their own contract (four eyes)
  * an action runs at most once per contract (unique action_runs.contract_id + state claim)
  * the outcome (pass / fail / inconclusive) comes only from measured SLIs after the action
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ..analysis.detect import samples_from_rows
from ..db import (ActionRunRow, ApprovalRow, ContractRow, EventRow, HypothesisRow, IncidentRow, TransitionRow,
                  VerificationRow)
from . import slo
from .executors import Executor
from .policy import CATALOGUE, POLICY_VERSION, RECOMMENDED_ACTION, evaluate

ALLOWED: dict[str, set[str]] = {
    "VALIDATED": {"AWAITING_APPROVAL", "READY_FOR_ACTION"},
    "AWAITING_APPROVAL": {"READY_FOR_ACTION", "REJECTED"},
    "READY_FOR_ACTION": {"EXECUTING"},
    "EXECUTING": {"VERIFYING", "FAILED"},
    "VERIFYING": {"SUCCEEDED", "FAILED", "INCONCLUSIVE"},
}
ACTIVE = {"AWAITING_APPROVAL", "READY_FOR_ACTION", "EXECUTING", "VERIFYING"}
FINAL = {"SUCCEEDED", "FAILED", "INCONCLUSIVE"}
OUTCOME_FOR_STATE = {"SUCCEEDED": "pass", "FAILED": "fail", "INCONCLUSIVE": "inconclusive"}


class ContractError(Exception):
    def __init__(self, code: str, status: int, detail: dict | None = None):
        super().__init__(code)
        self.code, self.status, self.detail = code, status, detail or {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _record(session: Session, row: ContractRow, from_state: str | None, to_state: str, actor: str,
            note: str = "", details: dict | None = None) -> None:
    session.add(TransitionRow(id=str(uuid.uuid4()), contract_id=row.id, from_state=from_state, to_state=to_state,
                              actor=actor, policy_version=POLICY_VERSION, note=note, details=details or {}, at=_now()))


def transition(session: Session, row: ContractRow, to: str, actor: str, note: str = "", details: dict | None = None) -> None:
    """Atomic compare-and-set: succeeds only if the contract is still in the state we read."""
    frm = row.state
    if to not in ALLOWED.get(frm, set()):
        raise ContractError("invalid_transition", 409, {"from": frm, "to": to})
    claimed = session.execute(update(ContractRow).where(ContractRow.id == row.id, ContractRow.state == frm).values(state=to))
    if claimed.rowcount != 1:
        raise ContractError("state_changed_concurrently", 409, {"expected": frm})
    _record(session, row, frm, to, actor, note, details)
    session.refresh(row)


def _get(session: Session, tenant_id: str, contract_id: str) -> ContractRow:
    row = session.get(ContractRow, contract_id)
    if row is None or row.tenant_id != tenant_id:
        raise ContractError("not_found", 404)
    return row


LATENCY_FLOOR_MS = 500  # blueprint default for checkout p95
LATENCY_BASELINE_FACTOR = 1.5  # recovered means within 1.5x of the pre-incident p95
P95_MIN_SAMPLES = 20


def default_slos(incident: IncidentRow) -> tuple[list[slo.Predicate], list[slo.Predicate], dict]:
    """Error rate <= 1% and p95 <= max(500 ms, 1.5 x this route's pre-incident p95).

    A fixed latency target can be unreachable where healthy requests are already slow (for
    example a remote database), so the target is anchored to the measured baseline. The
    basis is returned so it is recorded in the contract and can be audited."""
    baseline_p95 = {a["route"]: a.get("baseline_p95_ms") for a in (incident.summary or {}).get("anomalies", [])}
    success: list[slo.Predicate] = []
    basis: dict[str, dict] = {}
    for route in incident.routes:
        base = baseline_p95.get(route)
        target = max(LATENCY_FLOOR_MS, round(LATENCY_BASELINE_FACTOR * base)) if base else LATENCY_FLOOR_MS
        basis[route] = {"p95_target_ms": target, "baseline_p95_ms": base,
                        "rule": f"max({LATENCY_FLOOR_MS} ms, {LATENCY_BASELINE_FACTOR} x baseline p95)"}
        success.append(slo.Predicate(sli="error_rate", route=route, op="<=", threshold=0.01))
        # nearest-rank p95 of fewer than 20 samples is just the maximum: one request would decide it
        success.append(slo.Predicate(sli="p95_latency_ms", route=route, op="<=", threshold=target,
                                     min_samples=P95_MIN_SAMPLES))
    guard = [slo.Predicate(sli="error_rate", route=r, op="<=", threshold=0.01)
             for r in (incident.summary or {}).get("unaffected_routes", [])]
    return success, guard, basis


def create_contract(session: Session, tenant_id: str, incident_id: str, action_template: str | None, environment: str,
                    window_seconds: int, proposed_by: str) -> ContractRow:
    inc = session.get(IncidentRow, incident_id)
    if inc is None or inc.tenant_id != tenant_id:
        raise ContractError("not_found", 404)
    if inc.status != "open":
        raise ContractError("incident_not_open", 409, {"status": inc.status})

    hyps = sorted(session.scalars(select(HypothesisRow).where(HypothesisRow.incident_id == inc.id)),
                  key=lambda h: (h.status != "falsified", h.score), reverse=True)
    leader = hyps[0] if hyps else None
    warnings: list[str] = []
    if action_template is None:
        if inc.assessment != "leading_hypothesis" or leader is None:
            raise ContractError("incident_inconclusive_no_recommended_action", 409,
                                {"hint": "run /investigate, or name an action explicitly (it will be flagged)"})
        action_template = RECOMMENDED_ACTION.get(leader.cause_key)
        if action_template is None:
            raise ContractError("no_safe_action_for_cause", 409, {"cause": leader.cause_key})
    elif inc.assessment != "leading_hypothesis":
        warnings.append("incident_inconclusive: this action is not backed by a leading diagnosis")
    elif leader and RECOMMENDED_ACTION.get(leader.cause_key) != action_template:
        warnings.append("action_not_recommended_for_leading_hypothesis")

    active = session.scalar(select(ContractRow.id).where(ContractRow.incident_id == inc.id, ContractRow.state.in_(ACTIVE)))
    if active:
        raise ContractError("active_contract_exists", 409, {"contract_id": active})

    decision = evaluate(action_template, environment)
    success, guard, slo_basis = default_slos(inc)
    spec = CATALOGUE.get(action_template)
    contract_id = str(uuid.uuid4())
    body = {
        "contract_id": contract_id, "incident_id": inc.id, "action_template": action_template, "environment": environment,
        "preconditions": [{"check": "incident_open"}, {"check": "policy_still_allows"}],
        "approval_required": decision.approval_required, "timeout_seconds": 30,
        "success_conditions": [p.model_dump() for p in success], "safety_guardrails": [p.model_dump() for p in guard],
        "verification_window_seconds": window_seconds, "max_gap_seconds": window_seconds / 2, "slo_basis": slo_basis,
        "rollback_template": spec.rollback_template if spec else None, "outcome": "pending",
        "policy": {"version": POLICY_VERSION, "allowed": decision.allowed, "reasons": decision.reasons,
                   "blast_radius": decision.blast_radius},
        "basis": {"assessment": inc.assessment, "leading_cause": leader.cause_key if leader else None,
                  "hypothesis_score": leader.score if leader else None, "score_is_probability": False},
        "warnings": warnings, "verification_window": None,
    }
    row = ContractRow(id=contract_id, tenant_id=tenant_id, incident_id=inc.id, action_template=action_template[:60],
                      environment=environment, state="VALIDATED", outcome="pending", proposed_by=proposed_by,
                      contract=body, created_at=_now())
    session.add(row)
    session.flush()
    _record(session, row, None, "VALIDATED", proposed_by, "contract created")
    if not decision.allowed:
        row.state = "BLOCKED"
        _record(session, row, "VALIDATED", "BLOCKED", "policy-engine", "; ".join(decision.reasons), {"reasons": decision.reasons})
        session.flush()
        # Returned, not raised: the BLOCKED contract and its audit trail must be committed.
        # Callers map state == "BLOCKED" to an HTTP 403.
        return row
    transition(session, row, "AWAITING_APPROVAL" if decision.approval_required else "READY_FOR_ACTION", "policy-engine",
               "approval required by policy" if decision.approval_required else "no approval required")
    return row


def approve(session: Session, tenant_id: str, contract_id: str, reviewer: str, decision: str, comment: str) -> ContractRow:
    row = _get(session, tenant_id, contract_id)
    if row.state != "AWAITING_APPROVAL":
        raise ContractError("not_awaiting_approval", 409, {"state": row.state})
    if reviewer == row.proposed_by:
        raise ContractError("four_eyes_required", 403, {"detail": "the proposer cannot approve their own contract"})
    session.add(ApprovalRow(id=str(uuid.uuid4()), contract_id=row.id, reviewer=reviewer, decision=decision,
                            comment=comment, at=_now()))
    transition(session, row, "READY_FOR_ACTION" if decision == "approve" else "REJECTED", reviewer, comment)
    return row


def execute(sessions: sessionmaker, tenant_id: str, contract_id: str, actor: str, executor: Executor,
            approval_ttl_seconds: int = 1800) -> str:
    """Two short transactions around the executor call, so no DB lock is held during the action."""
    with sessions.begin() as s:
        row = _get(s, tenant_id, contract_id)
        if row.state != "READY_FOR_ACTION":
            raise ContractError("not_ready_for_action", 409, {"state": row.state})
        inc = s.get(IncidentRow, row.incident_id)
        if inc is None or inc.status != "open":
            raise ContractError("precondition_failed", 409, {"check": "incident_open"})
        approved_at = s.scalar(select(TransitionRow.at).where(TransitionRow.contract_id == row.id,
                                                              TransitionRow.to_state == "READY_FOR_ACTION")
                               .order_by(TransitionRow.at.desc()))
        if approved_at is not None and (_now() - _aware(approved_at)).total_seconds() > approval_ttl_seconds:
            raise ContractError("approval_expired", 409, {"ttl_seconds": approval_ttl_seconds,
                                                          "hint": "propose a new contract; conditions may have changed"})
        decision = evaluate(row.action_template, row.environment)  # policy is re-checked at execution time
        if not decision.allowed:
            raise ContractError("blocked_by_policy", 403, {"reasons": decision.reasons})
        transition(s, row, "EXECUTING", actor, "action started")
        run = ActionRunRow(id=str(uuid.uuid4()), contract_id=row.id, action_template=row.action_template,
                           executor=executor.name, started_at=_now(), status="running", output={})
        s.add(run)
        try:
            s.flush()
        except IntegrityError as exc:  # unique(contract_id): a second execution can never start
            raise ContractError("already_executed", 409) from exc
        action, env, timeout, run_id = row.action_template, row.environment, row.contract["timeout_seconds"], run.id

    result = executor.run(action, env, timeout)

    with sessions.begin() as s:
        row = _get(s, tenant_id, contract_id)
        run = s.get(ActionRunRow, run_id)
        run.ended_at, run.status, run.output = _now(), "succeeded" if result.ok else "failed", result.output
        if result.ok:
            body = dict(row.contract)
            window = body["verification_window_seconds"]
            body["verification_window"] = {"start": run.ended_at.isoformat(), "end": (run.ended_at + timedelta(seconds=window)).isoformat()}
            row.contract = body
            transition(s, row, "VERIFYING", actor, "action finished; waiting for the verification window to complete")
        else:
            body = dict(row.contract)
            body["outcome"] = row.outcome = "fail"
            row.contract = body
            transition(s, row, "FAILED", actor, "action_failed: no recovery was attempted", result.output)
        return row.state


def verify(session: Session, tenant_id: str, contract_id: str, actor: str, as_of: datetime) -> dict:
    """Evaluate the SLO contract. Returns {'outcome': pending|pass|fail|inconclusive, ...}."""
    row = _get(session, tenant_id, contract_id)
    if row.state in FINAL:  # idempotent: the stored verdict is final
        last = session.scalars(select(VerificationRow).where(VerificationRow.contract_id == row.id)
                               .order_by(VerificationRow.evaluated_at.desc())).first()
        return {"outcome": row.outcome, "state": row.state, "reason": last.reason if last else "", "final": True}
    if row.state != "VERIFYING":
        raise ContractError("not_verifying", 409, {"state": row.state})
    window = row.contract["verification_window"]
    start, end = datetime.fromisoformat(window["start"]), datetime.fromisoformat(window["end"])
    as_of = _aware(as_of)
    if as_of < end:
        return {"outcome": "pending", "state": row.state, "final": False,
                "reason": f"verification window ends at {end.isoformat()}; the action having run proves nothing yet"}

    routes = {p["route"] for p in row.contract["success_conditions"] + row.contract["safety_guardrails"]}
    rows = session.scalars(select(EventRow).where(EventRow.tenant_id == tenant_id, EventRow.event_time >= start,
                                                  EventRow.event_time <= end))
    samples = [s for s in samples_from_rows(rows) if s.route in routes]
    success = [slo.Predicate(**p) for p in row.contract["success_conditions"]]
    guards = [slo.Predicate(**p) for p in row.contract["safety_guardrails"]]
    outcome, reason, details = slo.evaluate(success, guards, samples, _aware(start), _aware(end),
                                            row.contract["max_gap_seconds"])
    session.add(VerificationRow(id=str(uuid.uuid4()), contract_id=row.id, window_start=start, window_end=end,
                                evaluated_at=_now(), outcome=outcome, reason=reason, predicates=details))
    final_state = {"pass": "SUCCEEDED", "fail": "FAILED", "inconclusive": "INCONCLUSIVE"}[outcome]
    body = dict(row.contract)
    body["outcome"] = row.outcome = outcome
    row.contract = body
    transition(session, row, final_state, actor, reason)
    if outcome == "pass":
        inc = session.get(IncidentRow, row.incident_id)
        if inc:
            inc.status = "resolved"
    return {"outcome": outcome, "state": row.state, "reason": reason, "final": True, "predicates": details}


def get_contract(session: Session, tenant_id: str, contract_id: str) -> dict:
    row = _get(session, tenant_id, contract_id)
    q = lambda model, order: list(session.scalars(select(model).where(model.contract_id == row.id).order_by(order)))
    transitions, approvals = q(TransitionRow, TransitionRow.at), q(ApprovalRow, ApprovalRow.at)
    run = session.scalar(select(ActionRunRow).where(ActionRunRow.contract_id == row.id))
    verifications = q(VerificationRow, VerificationRow.evaluated_at)
    return {
        "id": row.id, "incident_id": row.incident_id, "action_template": row.action_template,
        "environment": row.environment, "state": row.state, "outcome": row.outcome, "proposed_by": row.proposed_by,
        "contract": row.contract,
        "transitions": [{"from": t.from_state, "to": t.to_state, "actor": t.actor, "policy_version": t.policy_version,
                         "note": t.note, "at": t.at.isoformat()} for t in transitions],
        "approvals": [{"reviewer": a.reviewer, "decision": a.decision, "comment": a.comment, "at": a.at.isoformat()} for a in approvals],
        "action_run": None if run is None else {"executor": run.executor, "status": run.status, "output": run.output,
                                                "started_at": run.started_at.isoformat(),
                                                "ended_at": run.ended_at.isoformat() if run.ended_at else None},
        "verifications": [{"outcome": v.outcome, "reason": v.reason, "window_start": v.window_start.isoformat(),
                           "window_end": v.window_end.isoformat(), "predicates": v.predicates} for v in verifications],
    }
