"""HTTP routes for recovery contracts. Registered by create_app()."""
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..config import Settings
from . import contracts
from .contracts import ContractError
from .executors import Executor
from .policy import CATALOGUE, RECOMMENDED_ACTION

class CreateContract(BaseModel):
    incident_id: str = Field(max_length=36)
    # Optional: default is the action recommended for the leading hypothesis.
    action_template: str | None = Field(default=None, max_length=60, pattern=r"^[a-z_]+$")
    environment: Literal["sandbox", "demo", "production"] | None = None
    verification_window_seconds: int = Field(default=60, ge=30, le=900)


class Decision(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str = Field(default="", max_length=500)
    # Needed to approve when the rehearsal predicted the action would not meet the contract.
    acknowledge_rehearsal_failure: bool = False


class RollbackRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


def register(app: FastAPI, settings: Settings, sessions, auth, executor: Executor) -> None:
    # Who acts is the logged-in operator (see app/auth.py); approving needs the approver role.
    actor, approver = auth.actor("act"), auth.actor("approve")

    def fail(exc: ContractError) -> JSONResponse:
        return JSONResponse({"error": exc.code, **exc.detail}, status_code=exc.status)

    deps = [Depends(auth.require("read"))]
    tenant = settings.default_tenant_id

    @app.get("/api/v1/recovery-actions", dependencies=deps)
    def actions() -> dict:
        return {"actions": [{"id": a.id, "description": a.description, "target_service": a.target_service,
                             "risk": a.risk, "environments": list(a.environments), "approval_required": a.approval_required,
                             "disruptive": a.disruptive, "rollback_template": a.rollback_template,
                             "reverts": a.reverts} for a in CATALOGUE.values()],
                "recommended_for_cause": RECOMMENDED_ACTION}

    @app.get("/api/v1/recovery-contracts", dependencies=deps)
    def list_contracts(incident_id: Annotated[str, Query(max_length=36)]):
        from sqlalchemy import select

        from ..db import ContractRow
        with sessions() as s:
            ids = list(s.scalars(select(ContractRow.id).where(ContractRow.tenant_id == tenant,
                                                              ContractRow.incident_id == incident_id)
                                 .order_by(ContractRow.created_at)))
            return [contracts.get_contract(s, tenant, i) for i in ids]

    @app.post("/api/v1/recovery-contracts", status_code=201)
    def create(body: CreateContract, who: Annotated[str, Depends(actor)]):
        env = body.environment or settings.default_environment
        try:
            with sessions.begin() as s:
                row = contracts.create_contract(s, tenant, body.incident_id, body.action_template, env,
                                                body.verification_window_seconds, who)
                out = contracts.get_contract(s, tenant, row.id)
        except ContractError as exc:
            return fail(exc)
        if out["state"] == "BLOCKED":
            return JSONResponse({"error": "blocked_by_policy", "contract_id": out["id"],
                                 "reasons": out["contract"]["policy"]["reasons"]}, status_code=403)
        return out

    @app.post("/api/v1/recovery-contracts/{contract_id}/approve")
    def approve(contract_id: str, body: Decision, who: Annotated[str, Depends(approver)]):
        try:
            with sessions.begin() as s:
                contracts.approve(s, tenant, contract_id, who, body.decision, body.comment,
                                  body.acknowledge_rehearsal_failure)
                return contracts.get_contract(s, tenant, contract_id)
        except ContractError as exc:
            return fail(exc)

    @app.post("/api/v1/recovery-contracts/{contract_id}/execute")
    def execute(contract_id: str, who: Annotated[str, Depends(actor)]):
        try:
            contracts.execute(sessions, tenant, contract_id, who, executor, settings.approval_ttl_seconds)
            with sessions() as s:
                return contracts.get_contract(s, tenant, contract_id)
        except ContractError as exc:
            return fail(exc)

    @app.post("/api/v1/recovery-contracts/{contract_id}/rehearse")
    def rehearse(contract_id: str, who: Annotated[str, Depends(actor)]):
        try:
            with sessions.begin() as s:
                contracts.rehearse_contract(s, tenant, contract_id, who)
                return contracts.get_contract(s, tenant, contract_id)
        except ContractError as exc:
            return fail(exc)

    @app.post("/api/v1/recovery-contracts/{contract_id}/rollback")
    def rollback(contract_id: str, who: Annotated[str, Depends(actor)], body: RollbackRequest | None = None):
        try:
            contracts.rollback(sessions, tenant, contract_id, who, executor, (body or RollbackRequest()).reason)
            with sessions() as s:
                return contracts.get_contract(s, tenant, contract_id)
        except ContractError as exc:
            return fail(exc)

    @app.post("/api/v1/recovery-contracts/{contract_id}/verify")
    def verify(contract_id: str, who: Annotated[str, Depends(actor)],
               as_of: Annotated[datetime | None, Query(description="Evaluate as of this time (default: now)")] = None):
        when = as_of or datetime.now(timezone.utc)
        if when.tzinfo is None:
            raise HTTPException(status_code=422, detail="as_of must include a timezone")
        try:
            with sessions.begin() as s:
                return contracts.verify(s, tenant, contract_id, who, when)
        except ContractError as exc:
            return fail(exc)

    @app.get("/api/v1/recovery-contracts/{contract_id}", dependencies=deps)
    def read(contract_id: str):
        try:
            with sessions() as s:
                return contracts.get_contract(s, tenant, contract_id)
        except ContractError as exc:
            return fail(exc)

    @app.get("/api/v1/recovery-contracts/{contract_id}/verification", dependencies=deps)
    def read_verification(contract_id: str):
        try:
            with sessions() as s:
                full = contracts.get_contract(s, tenant, contract_id)
        except ContractError as exc:
            return fail(exc)
        return {"state": full["state"], "outcome": full["outcome"], "window": full["contract"]["verification_window"],
                "verifications": full["verifications"]}
