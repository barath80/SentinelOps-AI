"""Central audit log: who changed what, outside the contract state machine (which has its own trail).

Rows are append-only. GET /api/v1/audit merges them with contract transitions so one page shows
every security-relevant change in time order.
"""

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import AuditRow, ContractRow, TransitionRow


def record(session: Session, actor: str, action: str, target: str = "", details: dict | None = None) -> None:
    session.add(AuditRow(id=str(uuid.uuid4()), at=datetime.now(timezone.utc), actor=actor or "unknown",
                         action=action, target=target[:200], details=details or {}))


def register(app: FastAPI, tenant_id: str, sessions, auth) -> None:
    @app.get("/api/v1/audit")
    def audit(_p: Annotated[object, Depends(auth.require("approve"))],
              limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[dict]:
        with sessions() as s:
            rows = [{"at": a.at.isoformat(), "actor": a.actor, "action": a.action, "target": a.target, "details": a.details}
                    for a in s.scalars(select(AuditRow).order_by(AuditRow.at.desc()).limit(limit))]
            q = (select(TransitionRow, ContractRow).join(ContractRow, ContractRow.id == TransitionRow.contract_id)
                 .where(ContractRow.tenant_id == tenant_id).order_by(TransitionRow.at.desc()).limit(limit))
            rows += [{"at": t.at.isoformat(), "actor": t.actor, "action": f"contract.{t.to_state.lower()}",
                      "target": f"{c.action_template} ({c.id[:8]})", "details": {"from": t.from_state, "note": t.note}}
                     for t, c in s.execute(q)]
        aware = lambda iso: datetime.fromisoformat(iso) if datetime.fromisoformat(iso).tzinfo else datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
        return sorted(rows, key=lambda r: aware(r["at"]), reverse=True)[:limit]
