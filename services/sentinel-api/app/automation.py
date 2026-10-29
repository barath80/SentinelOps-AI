"""Automatic remediation, opt-in per cause, always through the normal recovery contract.

Modes per cause (AutomationPolicyRow); anything without a policy is `manual`:
The global switch (admin, PUT /api/v1/automation) is the kill switch for everything below: while it
is off, no cause is proposed or executed automatically, whatever its policy says.

  manual   SentinelOps diagnoses and notifies; people propose, approve and execute.
  propose  SentinelOps opens the recommended contract itself; a person still approves it.
  auto     SentinelOps proposes, approves on the policy's authority and executes, but only when:
             * automation is switched on globally (admin) and allowed by SENTINEL_AUTOMATION_ALLOWED,
             * the leading cause survived falsification (a decisive diagnostic, strength >= 0.8),
             * the rehearsal passed (inconclusive or failed means a person decides),
             * the action's declared risk is within the policy's max_risk,
             * fewer than SENTINEL_AUTOMATION_MAX_ACTIONS_PER_HOUR actions ran in the last hour.
           Policy, production blocking, verification from telemetry and the audit trail all still
           apply. With auto_rollback, a contract it executed is rolled back when a guardrail breaks.

Every step is recorded in automation_runs and announced on the `automation.action` channel.
Verification of any contract whose window has closed also runs here (read-only, for all contracts).
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import audit, notify
from .db import (AutomationPolicyRow, AutomationRunRow, ContractRow, EvidenceRow, HypothesisRow, IncidentRow)
from .recovery import contracts
from .recovery.contracts import ContractError
from .recovery.policy import CATALOGUE, RECOMMENDED_ACTION

GLOBAL = "__global__"
RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
AUTOMATION_ACTOR = "automation"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_on(session: Session, settings) -> bool:
    g = session.get(AutomationPolicyRow, GLOBAL)
    return bool(settings.automation_allowed and g and g.mode == "auto")


def policy(session: Session, cause: str) -> AutomationPolicyRow | None:
    return session.get(AutomationPolicyRow, cause)


def _log(session: Session, incident_id: str, contract_id: str | None, step: str, outcome: str, reason: str = "",
         dedupe: bool = False) -> dict:
    """Record a step. With dedupe, a step that repeats the incident's last record is reported but not
    stored again: a skip re-evaluated every pass must not bury real actions in the run history."""
    last = session.scalars(select(AutomationRunRow).where(AutomationRunRow.incident_id == incident_id)
                           .order_by(AutomationRunRow.at.desc()).limit(1)).first() if dedupe else None
    if not (last and (last.contract_id, last.step, last.outcome, last.reason) == (contract_id, step, outcome, reason)):
        session.add(AutomationRunRow(id=str(uuid.uuid4()), at=_now(), incident_id=incident_id, contract_id=contract_id,
                                     step=step, outcome=outcome, reason=reason))
    return {"incident_id": incident_id, "contract_id": contract_id, "step": step, "outcome": outcome, "reason": reason}


def _confirmed(session: Session, leader: HypothesisRow) -> bool:
    """The leader passed a decisive diagnostic test: it survived an attempt to falsify it."""
    return any(e.created_by.startswith("diagnostic:") and e.relation == "supports" and e.strength >= 0.8
               for e in session.scalars(select(EvidenceRow).where(EvidenceRow.hypothesis_id == leader.id)))


def _actions_last_hour(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(AutomationRunRow).where(
        AutomationRunRow.step == "execute", AutomationRunRow.at >= _now() - timedelta(hours=1))) or 0


def verify_due(sessions, settings, now: datetime | None = None) -> list[dict]:
    """Close every verification window that has ended. Read-only on the world: it measures telemetry."""
    now = now or _now()
    out = []
    with sessions() as s:
        due = [(c.id, c.incident_id) for c in s.scalars(select(ContractRow).where(
            ContractRow.tenant_id == settings.default_tenant_id, ContractRow.state == "VERIFYING"))
            if datetime.fromisoformat((c.contract.get("verification_window") or {}).get("end", "9999-01-01T00:00:00+00:00")) <= now]
    for cid, iid in due:
        try:
            with sessions.begin() as s:
                res = contracts.verify(s, settings.default_tenant_id, cid, "automation:verifier", now)
                out.append(_log(s, iid, cid, "verify", res["outcome"], res.get("reason", "")))
        except ContractError as exc:  # someone else moved it meanwhile: skip it, carry on with the pass
            with sessions.begin() as s:
                out.append(_log(s, iid, cid, "verify", "skipped", exc.code))
    return out


def run(sessions, settings, executor, now: datetime | None = None) -> list[dict]:
    """One automation pass. Safe to run often: every step re-checks its preconditions."""
    now = now or _now()
    out = verify_due(sessions, settings, now)
    with sessions() as s:
        if not is_on(s, settings):
            return out
    tenant = settings.default_tenant_id

    # Roll back contracts automation executed whose verification breached a guardrail.
    with sessions() as s:
        failed = [(c.id, c.incident_id, c.contract.get("diagnosed_cause")) for c in s.scalars(select(ContractRow).where(
            ContractRow.tenant_id == tenant, ContractRow.state == "FAILED", ContractRow.proposed_by == AUTOMATION_ACTOR))
            if c.contract.get("rollback_recommended") and c.contract.get("pre_action_snapshot")]
    for cid, iid, cause in failed:
        with sessions() as s:
            pol = policy(s, cause or "")
            if not (pol and pol.mode == "auto" and pol.auto_rollback):
                continue
        try:
            state = contracts.rollback(sessions, tenant, cid, AUTOMATION_ACTOR, executor, "automation: a guardrail was breached")
            with sessions.begin() as s:
                out.append(_log(s, iid, cid, "rollback", state))
        except ContractError as exc:
            with sessions.begin() as s:
                out.append(_log(s, iid, cid, "rollback", "refused", exc.code, dedupe=True))

    # Act on open incidents with a leading cause.
    with sessions() as s:
        incidents = [i.id for i in s.scalars(select(IncidentRow).where(
            IncidentRow.tenant_id == tenant, IncidentRow.status == "open", IncidentRow.assessment == "leading_hypothesis"))]
    for iid in incidents:
        out += _act(sessions, settings, executor, iid)
    return out


def _act(sessions, settings, executor, iid: str) -> list[dict]:
    tenant = settings.default_tenant_id
    with sessions.begin() as s:
        inc = s.get(IncidentRow, iid)
        leader = s.scalars(select(HypothesisRow).where(HypothesisRow.incident_id == iid).order_by(HypothesisRow.score.desc())).first()
        if not leader or leader.status != "leading":
            return []
        pol = policy(s, leader.cause_key)
        if not pol or pol.mode == "manual":
            return []
        if s.scalar(select(ContractRow.id).where(ContractRow.incident_id == iid, ContractRow.proposed_by == AUTOMATION_ACTOR)):
            return []  # automation acts at most once per incident; people take it from there
        action = RECOMMENDED_ACTION.get(leader.cause_key)
        if not action:
            return [_log(s, iid, None, "skip", "no_recommended_action", leader.cause_key, dedupe=True)]
        if not _confirmed(s, leader):
            return [_log(s, iid, None, "skip", "not_confirmed", "the leading cause has not survived a decisive diagnostic yet", dedupe=True)]
        if pol.mode == "auto" and _actions_last_hour(s) >= settings.automation_max_actions_per_hour:
            return [_log(s, iid, None, "skip", "rate_capped", f"{settings.automation_max_actions_per_hour} actions in the last hour", dedupe=True)]
        try:
            row = contracts.create_contract(s, tenant, iid, None, settings.default_environment, 60, AUTOMATION_ACTOR)
        except ContractError as exc:
            return [_log(s, iid, None, "propose", "refused", exc.code, dedupe=True)]
        body = dict(row.contract)
        body["diagnosed_cause"] = leader.cause_key
        row.contract = body
        cid, state = row.id, row.state
        steps = [_log(s, iid, cid, "propose", state, f"{action} for {leader.cause_key} (policy {pol.mode})")]
        notify.dispatch(s, "automation.action", {**notify.incident_payload(s, inc, notify.PUBLIC_URL),
                                                 "action": action, "state": state, "reason": f"policy {pol.mode}"})
        if pol.mode != "auto" or state != "AWAITING_APPROVAL":
            return steps
        rehearsal = (row.contract.get("rehearsal") or {}).get("outcome")
        risk = CATALOGUE[action].risk
        if rehearsal != "pass":
            steps.append(_log(s, iid, cid, "skip", "needs_person", f"rehearsal {rehearsal}: a person must approve"))
            return steps
        if RISK_ORDER.get(risk, 2) > RISK_ORDER.get(pol.max_risk, 0):
            steps.append(_log(s, iid, cid, "skip", "needs_person", f"risk {risk} above the policy's {pol.max_risk}"))
            return steps
        contracts.approve(s, tenant, cid, f"policy:{leader.cause_key}", "approve",
                          f"approved by automation policy set by {pol.updated_by} at {pol.updated_at.isoformat()}")
    try:
        state = contracts.execute(sessions, tenant, cid, AUTOMATION_ACTOR, executor, settings.approval_ttl_seconds)
        with sessions.begin() as s:
            steps.append(_log(s, iid, cid, "execute", state))
    except ContractError as exc:
        with sessions.begin() as s:
            steps.append(_log(s, iid, cid, "execute", "refused", exc.code))
    return steps


# ---- API ----------------------------------------------------------------------------------------

class PolicyChange(BaseModel):
    mode: Literal["manual", "propose", "auto"]
    auto_rollback: bool = True
    max_risk: Literal["low", "medium"] = "low"


class Switch(BaseModel):
    enabled: bool


def register(app: FastAPI, settings, sessions, auth, executor) -> None:
    admin = auth.require("admin")

    @app.get("/api/v1/automation")
    def state(_p: Annotated[object, Depends(auth.require("read"))]) -> dict:
        with sessions() as s:
            pols = {p.cause_key: p for p in s.scalars(select(AutomationPolicyRow))}
            runs = list(s.scalars(select(AutomationRunRow).order_by(AutomationRunRow.at.desc()).limit(50)))
            return {
                "allowed": settings.automation_allowed, "enabled": is_on(s, settings),
                "max_actions_per_hour": settings.automation_max_actions_per_hour,
                "actions_last_hour": _actions_last_hour(s),
                "policies": [{"cause": cause, "action": action, "risk": CATALOGUE[action].risk,
                              "mode": pols[cause].mode if cause in pols else "manual",
                              "auto_rollback": pols[cause].auto_rollback if cause in pols else True,
                              "max_risk": pols[cause].max_risk if cause in pols else "low",
                              "updated_by": pols[cause].updated_by if cause in pols else None}
                             for cause, action in sorted(RECOMMENDED_ACTION.items())],
                "recent_runs": [{"at": r.at.isoformat(), "incident_id": r.incident_id, "contract_id": r.contract_id,
                                 "step": r.step, "outcome": r.outcome, "reason": r.reason} for r in runs],
            }

    @app.put("/api/v1/automation/policies/{cause}")
    def set_policy(cause: str, body: PolicyChange, p: Annotated[object, Depends(admin)]) -> dict:
        if cause not in RECOMMENDED_ACTION:
            raise HTTPException(status_code=404, detail="no_recommended_action_for_cause")
        with sessions.begin() as s:
            row = s.get(AutomationPolicyRow, cause) or AutomationPolicyRow(cause_key=cause)
            row.mode, row.auto_rollback, row.max_risk = body.mode, body.auto_rollback, body.max_risk
            row.updated_by, row.updated_at = p.name, _now()
            s.merge(row)
            audit.record(s, p.name, "automation.policy_changed", cause, body.model_dump())
        return state(p)

    @app.put("/api/v1/automation")
    def switch(body: Switch, p: Annotated[object, Depends(admin)]) -> dict:
        if body.enabled and not settings.automation_allowed:
            raise HTTPException(status_code=403, detail="automation_not_allowed_on_this_deployment")
        with sessions.begin() as s:
            row = s.get(AutomationPolicyRow, GLOBAL) or AutomationPolicyRow(cause_key=GLOBAL)
            row.mode, row.updated_by, row.updated_at = ("auto" if body.enabled else "manual"), p.name, _now()
            row.auto_rollback, row.max_risk = True, "low"
            s.merge(row)
            audit.record(s, p.name, "automation.enabled" if body.enabled else "automation.disabled", "global")
        return state(p)

    @app.post("/api/v1/automation/run")
    def run_now(p: Annotated[object, Depends(admin)]) -> dict:
        results = run(sessions, settings, executor)
        notify.flush(sessions, settings.notify_allow_private, settings.notify_allow_private)
        return {"steps": results}
