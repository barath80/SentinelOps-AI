"""Incident-to-prevention compiler.

Once a cause is CONFIRMED (the recommended fix for the leading hypothesis passed SLO verification
and the incident is resolved), propose artifacts that would have caught or prevented it: a
regression test, an alert rule, a runbook amendment, and a follow-up for each piece of missing
evidence. Generation is deterministic templating (no LLM). Every artifact:
  * links to the incident, the verified contract and the ledger evidence that motivated it
  * passes static checks before it is stored (it is still untrusted text, never executed here)
  * starts as `proposed` and changes only through an explicit human review; nothing is merged,
    deployed or run by the system.
"""
import ast
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from .db import ContractRow, EvidenceRow, HypothesisRow, IncidentRow, PreventionArtifactRow

ALLOWED_IMPORTS = {"os", "uuid", "time", "statistics", "httpx", "pytest"}
FORBIDDEN_NAMES = {"eval", "exec", "compile", "__import__", "open", "input", "globals", "locals"}
SECRET_PATTERN = re.compile(r"(npg_[A-Za-z0-9]+|postgres(ql)?://\S+:\S+@|Bearer\s+[A-Za-z0-9]{16,}|sk-[A-Za-z0-9]{10,})")
_ACTOR = re.compile(r"^[A-Za-z0-9_.@-]{1,100}$")


class PreventionError(Exception):
    def __init__(self, code: str, status: int, detail: dict | None = None):
        super().__init__(code)
        self.code, self.status, self.detail = code, status, detail or {}


# ---- static checks (generated text is untrusted) ------------------------------------------------

def check_python(code: str) -> list[dict]:
    checks = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [{"name": "parses", "passed": False, "detail": str(exc)}]
    checks.append({"name": "parses", "passed": True, "detail": ""})
    bad_imports, bad_names, bad_os = [], [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bad_imports += [a.name for a in node.names if a.name.split(".")[0] not in ALLOWED_IMPORTS]
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
            bad_imports.append(node.module or "")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            bad_names.append(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os" \
                and node.attr != "environ":
            bad_os.append(node.attr)
    checks.append({"name": "imports_allow_listed", "passed": not bad_imports, "detail": ", ".join(bad_imports)})
    checks.append({"name": "no_dynamic_code_or_file_access", "passed": not (bad_names or bad_os),
                   "detail": ", ".join(bad_names + bad_os)})
    checks.append({"name": "no_secrets", "passed": not SECRET_PATTERN.search(code), "detail": ""})
    checks.append({"name": "targets_env_var_not_production", "passed": 'os.environ.get("SHOP_URL")' in code, "detail": ""})
    return checks


def check_json_rule(text: str) -> list[dict]:
    try:
        rule = json.loads(text)
    except ValueError as exc:
        return [{"name": "valid_json", "passed": False, "detail": str(exc)}]
    needed = {"name", "severity", "condition", "motivated_by"}
    return [{"name": "valid_json", "passed": True, "detail": ""},
            {"name": "has_required_fields", "passed": needed <= rule.keys(), "detail": ", ".join(sorted(needed - rule.keys()))},
            {"name": "no_secrets", "passed": not SECRET_PATTERN.search(text), "detail": ""}]


def check_markdown(text: str) -> list[dict]:
    return [{"name": "no_secrets", "passed": not SECRET_PATTERN.search(text), "detail": ""},
            {"name": "has_evidence_links", "passed": "evidence" in text.lower(), "detail": ""}]


# ---- templates ---------------------------------------------------------------------------------------

def _header(inc: IncidentRow, contract: ContractRow, cause: str, evidence_ids: list[str]) -> str:
    return (f"Incident {inc.id}; confirmed cause {cause} (recovery verified by contract {contract.id}).\n"
            f"Motivating evidence ids: {', '.join(evidence_ids) or 'none'}.")


def regression_test(inc, contract, cause, evidence_ids, route, p95_target_ms) -> str:
    head = _header(inc, contract, cause, evidence_ids)
    common = f'''"""Proposed regression test. UNREVIEWED GENERATED CODE: read it before running it.

{head}
Needs SHOP_URL pointing at a demo or staging shop. Never run it against production.
"""
import os
import time
import uuid

import httpx
import pytest

SHOP_URL = os.environ.get("SHOP_URL")
pytestmark = pytest.mark.skipif(not SHOP_URL, reason="set SHOP_URL to a demo/staging shop")


def _checkout(shop):
    assert shop.post("/api/cart", json={{"id": "p2", "qty": 1}}).status_code == 200
    started = time.perf_counter()
    res = shop.post("/api/checkout", headers={{"idempotency-key": str(uuid.uuid4())}})
    return res, (time.perf_counter() - started) * 1000
'''
    if cause == "release_regression":
        body = '''

def test_checkout_succeeds_for_a_normal_cart():
    with httpx.Client(base_url=SHOP_URL, timeout=15) as shop:
        res, _ = _checkout(shop)
        assert res.status_code == 201, res.text
'''
    elif cause == "payment_provider_timeout":
        body = '''

def test_checkout_completes_without_a_payment_timeout():
    with httpx.Client(base_url=SHOP_URL, timeout=15) as shop:
        res, ms = _checkout(shop)
        assert res.status_code == 201, res.text
        assert ms < 2500, f"checkout took {ms:.0f} ms; a payment timeout is about 3000 ms"
'''
    else:  # slow_dependency
        body = f'''

def test_checkout_p95_latency_stays_within_the_slo():
    with httpx.Client(base_url=SHOP_URL, timeout=20) as shop:
        times = []
        for _ in range(20):
            res, ms = _checkout(shop)
            assert res.status_code == 201, res.text
            times.append(ms)
    times.sort()
    p95 = times[int(len(times) * 0.95) - 1]
    assert p95 <= {p95_target_ms}, f"p95 {{p95:.0f}} ms exceeds {p95_target_ms} ms"
'''
    return common + body


def alert_rule(inc, contract, cause, evidence_ids, route, p95_target_ms) -> str:
    base = {"severity": "critical", "notify": "on-call", "route": route,
            "motivated_by": {"incident_id": inc.id, "contract_id": contract.id, "cause": cause, "evidence_ids": evidence_ids},
            "status": "proposed: not deployed"}
    if cause == "release_regression":
        rule = {"name": f"{route} error rate high after a release change", **base,
                "condition": {"sli": "error_rate", "route": route, "op": ">", "threshold": 0.05, "for_seconds": 120}}
    elif cause == "payment_provider_timeout":
        rule = {"name": "Payment provider timeouts", **base,
                "condition": {"signal": "log_message_count", "message": "payment_timeout", "op": ">=", "threshold": 3, "window_seconds": 60}}
    else:
        rule = {"name": f"{route} p95 latency above SLO", **base, "severity": "warning",
                "condition": {"sli": "p95_latency_ms", "route": route, "op": ">", "threshold": p95_target_ms, "for_seconds": 180}}
    return json.dumps(rule, indent=2)


def runbook(inc, contract, cause, evidence_ids, hypothesis, evidence, action) -> str:
    support = [e for e in evidence if e.relation == "supports"]
    lines = [f"# Runbook amendment: {hypothesis.title}", "", _header(inc, contract, cause, evidence_ids), "",
             "## Symptoms", "", inc.title, "", "## How it was diagnosed", ""]
    lines += [f"- {e.explanation} (evidence `{e.id}`, {e.created_by})" for e in support] or ["- (no supporting evidence recorded)"]
    lines += ["", "## Approved action", "",
              f"`{action}` (allow-listed; needs approval by someone other than the proposer).",
              "", "## Verify recovery", "",
              "Recovery means the contract's SLOs held for the whole verification window, measured from telemetry:"]
    lines += [f"- {p['sli']}({p['route']}) {p['op']} {p['threshold']}" for p in contract.contract["success_conditions"]]
    lines += ["", "## Rollback", "", "No rollback template is defined for this action yet. Define one before relying on it.",
              "", "## Owner", "", "To be assigned by the reviewer."]
    return "\n".join(lines)


def monitoring_gap(inc, contract, cause, evidence_ids, e: EvidenceRow) -> str:
    return "\n".join([f"# Monitoring gap: {e.explanation[:80]}", "", _header(inc, contract, cause, evidence_ids), "",
                      "## The gap", "", e.explanation, "",
                      "## Evidence", "", f"Ledger entry `{e.id}` (relation: missing, created by {e.created_by}).", "",
                      "## Proposed follow-up", "",
                      "Ingest the missing signal so the diagnosis can be tested instead of left unconfirmed."])


# ---- compiler -------------------------------------------------------------------------------------------

def compile_artifacts(session, tenant_id: str, incident_id: str) -> list[PreventionArtifactRow]:
    inc = session.get(IncidentRow, incident_id)
    if inc is None or inc.tenant_id != tenant_id:
        raise PreventionError("not_found", 404)
    existing = list(session.scalars(select(PreventionArtifactRow).where(PreventionArtifactRow.incident_id == inc.id)
                                    .order_by(PreventionArtifactRow.created_at)))
    if existing:  # idempotent
        return existing
    contract = session.scalars(select(ContractRow).where(ContractRow.incident_id == inc.id, ContractRow.state == "SUCCEEDED")
                               .order_by(ContractRow.created_at.desc())).first()
    if inc.status != "resolved" or contract is None:
        raise PreventionError("cause_not_confirmed", 409,
                              {"hint": "needs a recovery contract whose SLO verification passed (incident resolved)"})
    basis = contract.contract.get("basis", {})
    cause = basis.get("leading_cause")
    if not cause or any("not_recommended" in w or "not backed" in w for w in contract.contract.get("warnings", [])):
        raise PreventionError("cause_not_confirmed", 409, {"hint": "the verified action was not the recommended fix for a leading cause"})

    hyp = session.scalars(select(HypothesisRow).where(HypothesisRow.incident_id == inc.id, HypothesisRow.cause_key == cause)).first()
    evidence = list(session.scalars(select(EvidenceRow).where(EvidenceRow.incident_id == inc.id, EvidenceRow.hypothesis_id == hyp.id))) if hyp else []
    evidence_ids = [e.id for e in evidence if e.relation == "supports"]
    route = (inc.routes or ["/api/checkout"])[0]
    p95 = int(contract.contract.get("slo_basis", {}).get(route, {}).get("p95_target_ms", 500))
    sources = sorted({r for e in evidence for r in e.source_refs})

    specs = [
        ("regression_test", f"Regression test for {cause}", "python", regression_test(inc, contract, cause, evidence_ids, route, p95), check_python),
        ("alert_rule", f"Alert rule for {cause}", "json", alert_rule(inc, contract, cause, evidence_ids, route, p95), check_json_rule),
        ("runbook_amendment", f"Runbook amendment for {cause}", "markdown",
         runbook(inc, contract, cause, evidence_ids, hyp, evidence, contract.action_template) if hyp else "", check_markdown),
    ]
    for e in [e for e in evidence if e.relation == "missing"]:
        specs.append(("monitoring_gap", f"Close monitoring gap: {e.explanation[:60]}", "markdown",
                      monitoring_gap(inc, contract, cause, evidence_ids, e), check_markdown))

    rows = []
    for kind, title, language, content, checker in specs:
        if not content:
            continue
        checks = checker(content)
        rows.append(PreventionArtifactRow(
            id=str(uuid.uuid4()), incident_id=inc.id, contract_id=contract.id, artifact_type=kind, title=title[:200],
            language=language, content=content, evidence_ids=evidence_ids, source_event_ids=sources,
            review_status="proposed", checks=checks, checks_passed=all(c["passed"] for c in checks),
            created_at=datetime.now(timezone.utc)))
    session.add_all(rows)
    session.flush()
    return rows


def serialize(r: PreventionArtifactRow) -> dict:
    return {"id": r.id, "incident_id": r.incident_id, "contract_id": r.contract_id, "type": r.artifact_type,
            "title": r.title, "language": r.language, "content": r.content, "evidence_ids": r.evidence_ids,
            "source_event_ids": r.source_event_ids, "review_status": r.review_status, "reviewed_by": r.reviewed_by,
            "checks": r.checks, "checks_passed": r.checks_passed, "created_at": r.created_at.isoformat(),
            "note": "Generated text. Untrusted until a person has read it; the system never runs or merges it."}


class Review(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str = Field(default="", max_length=500)


def register(app: FastAPI, tenant_id: str, sessions, require_token) -> None:
    def actor(x_actor: Annotated[str | None, Header()] = None) -> str:
        if not x_actor or not _ACTOR.match(x_actor):
            raise HTTPException(status_code=400, detail="x_actor_header_required")
        return x_actor

    deps = [Depends(require_token)]

    @app.post("/api/v1/incidents/{incident_id}/prevention", dependencies=deps)
    def generate(incident_id: str, who: Annotated[str, Depends(actor)]):
        try:
            with sessions.begin() as s:
                return [serialize(r) for r in compile_artifacts(s, tenant_id, incident_id)]
        except PreventionError as exc:
            return JSONResponse({"error": exc.code, **exc.detail}, status_code=exc.status)

    @app.get("/api/v1/incidents/{incident_id}/prevention", dependencies=deps)
    def list_artifacts(incident_id: str):
        with sessions() as s:
            inc = s.get(IncidentRow, incident_id)
            if inc is None or inc.tenant_id != tenant_id:
                raise HTTPException(status_code=404, detail="not_found")
            rows = s.scalars(select(PreventionArtifactRow).where(PreventionArtifactRow.incident_id == incident_id)
                             .order_by(PreventionArtifactRow.created_at))
            return [serialize(r) for r in rows]

    @app.post("/api/v1/prevention-artifacts/{artifact_id}/review", dependencies=deps)
    def review(artifact_id: str, body: Review, who: Annotated[str, Depends(actor)]):
        with sessions.begin() as s:
            row = s.get(PreventionArtifactRow, artifact_id)
            inc = s.get(IncidentRow, row.incident_id) if row else None
            if row is None or inc is None or inc.tenant_id != tenant_id:
                raise HTTPException(status_code=404, detail="not_found")
            if row.review_status != "proposed":
                return JSONResponse({"error": "already_reviewed", "status": row.review_status}, status_code=409)
            if body.decision == "approve" and not row.checks_passed:
                return JSONResponse({"error": "static_checks_failed", "checks": row.checks}, status_code=409)
            row.review_status = "approved" if body.decision == "approve" else "rejected"
            row.reviewed_by, row.review_comment = who, body.comment
            return serialize(row)
