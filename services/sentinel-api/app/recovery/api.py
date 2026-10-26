"""HTTP routes for recovery contracts. Registered by create_app()."""
import re
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..config import Settings
from . import contracts
from .contracts import ContractError
from .executors import Executor
from .policy import CATALOGUE, RECOMMENDED_ACTION

_ACTOR = re.compile(r"^[A-Za-z0-9_.@-]{1,100}$")


class CreateContract(BaseModel):
    incident_id: str = Field(max_length=36)
    # Optional: default is the action recommended for the leading hypothesis.
    action_template: str | None = Field(default=None, max_length=60, pattern=r"^[a-z_]+$")
    environment: Literal["sandbox", "demo", "production"] | None = None
    verification_window_seconds: int = Field(default=60, ge=30, le=900)


class Decision(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str = Field(default="", max_length=500)


def register(app: FastAPI, settings: Settings, sessions, require_token, executor: Executor) -> None:
    def actor(x_actor: Annotated[str | None, Header()] = None) -> str:
        # Identity is asserted by the caller until a real OIDC provider is wired in (see docs).
        if not x_actor or not _ACTOR.match(x_actor):
            raise HTTPException(status_code=400, detail="x_actor_header_required")
        return x_actor

    def fail(exc: ContractError) -> JSONResponse:
        return JSONResponse({"error": exc.code, **exc.detail}, status_code=exc.status)

    deps = [Depends(require_token)]
    tenant = settings.default_tenant_id

    @app.get("/api/v1/recovery-actions", dependencies=deps)
    def actions() -> dict:
        return {"actions": [{"id": a.id, "description": a.description, "target_service": a.target_service,
                             "risk": a.risk, "environments": list(a.environments), "approval_required": a.approval_required,
                             "disruptive": a.disruptive} for a in CATALOGUE.values()],
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

    @app.post("/api/v1/recovery-contracts", dependencies=deps, status_code=201)
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

    @app.post("/api/v1/recovery-contracts/{contract_id}/approve", dependencies=deps)
    def approve(contract_id: str, body: Decision, who: Annotated[str, Depends(actor)]):
        try:
            with sessions.begin() as s:
                contracts.approve(s, tenant, contract_id, who, body.decision, body.comment)
                return contracts.get_contract(s, tenant, contract_id)
        except ContractError as exc:
            return fail(exc)

    @app.post("/api/v1/recovery-contracts/{contract_id}/execute", dependencies=deps)
    def execute(contract_id: str, who: Annotated[str, Depends(actor)]):
        try:
            contracts.execute(sessions, tenant, contract_id, who, executor)
            with sessions() as s:
                return contracts.get_contract(s, tenant, contract_id)
        except ContractError as exc:
            return fail(exc)

    @app.post("/api/v1/recovery-contracts/{contract_id}/verify", dependencies=deps)
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
