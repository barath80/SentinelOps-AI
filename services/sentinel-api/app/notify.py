"""Team notifications: Slack-compatible and generic webhooks, delivered through an outbox.

Domain code calls dispatch() inside the transaction that makes the change, so a notification is
recorded exactly when its change commits and never for a change that rolled back. A sender loop
(and the maintenance tick) delivers pending rows with retries and backoff.

Security:
  * webhook URLs must be https and must not resolve to a private, loopback or link-local address
    (checked when a channel is created and again before every send, so DNS cannot be switched later);
  * the URL is never returned by the API, only its host;
  * generic webhooks are signed: X-SentinelOps-Signature: sha256=HMAC(channel secret, body);
  * message text is built from stored values only; nothing in it is executed anywhere.
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Callable, Literal
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from . import audit
from .db import EvidenceRow, HypothesisRow, IncidentRow, NotificationChannelRow, NotificationRow

log = logging.getLogger("sentinelops.notify")

EVENTS = {
    "incident.opened": "A new incident was raised",
    "incident.diagnosed": "An investigation reached a leading cause",
    "approval.needed": "A recovery contract is waiting for an approver",
    "action.blocked": "Policy blocked a proposed action",
    "recovery.succeeded": "Verification passed: the incident is resolved",
    "recovery.failed": "Verification failed or was inconclusive",
    "rollback.done": "A failed recovery was rolled back",
    "rollback.failed": "A rollback failed: manual intervention needed",
    "automation.action": "Automation proposed or executed an action",
    "throttling.detected": "Requests are being rejected with 429 (rate limited)",
    "telemetry.quality": "Telemetry cannot be trusted (for example a clock running ahead)",
    "slo.burn": "A route is burning its error budget fast (14.4x or more)",
}
# Base URL for links in messages; set from SENTINEL_PUBLIC_URL by create_app().
PUBLIC_URL = ""
MAX_ATTEMPTS = 5
LEASE_S = 60  # a claimed notification is retried after this if its sender never reports back
BACKOFF_S = 30


class Unsafe(ValueError):
    pass


def check_url(url: str, allow_private: bool = False, allow_http: bool = False) -> str:
    """Raise Unsafe unless the URL is https and every address it resolves to is public."""
    u = urlparse(url)
    if u.scheme not in (("https", "http") if allow_http else ("https",)) or not u.hostname:
        raise Unsafe("webhook URL must be https://host/...")
    if u.username or u.password:
        raise Unsafe("credentials in the URL are not allowed")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise Unsafe(f"cannot resolve {u.hostname}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not allow_private and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                                  or ip.is_multicast or ip.is_unspecified):
            raise Unsafe(f"{u.hostname} resolves to a non-public address")
    return u.hostname


def _subscribers(session: Session, event: str) -> list[NotificationChannelRow]:
    return [c for c in session.scalars(select(NotificationChannelRow).where(NotificationChannelRow.enabled.is_(True)))
            if event in (c.events or [])]


def dispatch(session: Session, event: str, payload: dict, dedupe_seconds: int = 0) -> int:
    """Queue `event` for every subscribed channel. Returns how many rows were queued."""
    if event not in EVENTS:
        raise ValueError(event)
    now = datetime.now(timezone.utc)
    queued = 0
    for ch in _subscribers(session, event):
        if dedupe_seconds:
            key = payload.get("dedupe_key")
            recent = session.scalars(select(NotificationRow).where(
                NotificationRow.channel_id == ch.id, NotificationRow.event == event,
                NotificationRow.created_at >= now - timedelta(seconds=dedupe_seconds)))
            if any((r.payload or {}).get("dedupe_key") == key for r in recent):
                continue
        session.add(NotificationRow(id=str(uuid.uuid4()), channel_id=ch.id, event=event, payload=payload,
                                    status="pending", attempts=0, created_at=now, next_attempt_at=now))
        queued += 1
    return queued


def incident_payload(session: Session, inc: IncidentRow, public_url: str = "") -> dict:
    """What the team needs to act: the symptom, the leading cause and the evidence behind it."""
    hyps = sorted(session.scalars(select(HypothesisRow).where(HypothesisRow.incident_id == inc.id)),
                  key=lambda h: (h.status != "falsified", h.score), reverse=True)
    top = hyps[0] if hyps else None
    evidence = []
    if top:
        evidence = [e.explanation for e in sorted(session.scalars(select(EvidenceRow).where(
            EvidenceRow.hypothesis_id == top.id, EvidenceRow.relation == "supports")), key=lambda e: -e.strength)][:3]
    containment = ((inc.summary or {}).get("propagation") or {}).get("earliest_containment") or {}
    return {"incident_id": inc.id, "title": inc.title, "severity": inc.severity, "status": inc.status,
            "assessment": inc.assessment, "leading_cause": top.cause_key if top and inc.assessment == "leading_hypothesis" else None,
            "score": top.score if top else None, "score_is_probability": False, "evidence": evidence,
            "contain_at": containment.get("node"), "started_at": inc.started_at.isoformat(),
            "link": f"{public_url.rstrip('/')}/ui/#/incident/{inc.id}/summary" if public_url else None}


def text_for(event: str, p: dict) -> str:
    """A plain-language message (Slack format: mrkdwn-safe plain text)."""
    head = f"[SentinelOps] {EVENTS.get(event, event)}"
    lines = [head]
    if p.get("title"):
        lines.append(f"{(p.get('severity') or '').upper()} {p['title']}")
    if p.get("leading_cause"):
        lines.append(f"Leading cause: {p['leading_cause']} (score {p.get('score')}, a ranking, not a probability)")
    elif p.get("assessment") == "inconclusive":
        lines.append("No cause is clearly supported yet: investigate before acting.")
    for e in p.get("evidence") or []:
        lines.append(f"  - {e}")
    for key, label in (("contain_at", "Contain at"), ("action", "Action"), ("state", "State"), ("reason", "Reason"),
                       ("message", "Detail")):
        if p.get(key):
            lines.append(f"{label}: {p[key]}")
    if p.get("link"):
        lines.append(p["link"])
    return "\n".join(lines)[:3500]


def _body(ch: NotificationChannelRow, row: NotificationRow) -> bytes:
    if ch.kind == "slack":
        return json.dumps({"text": text_for(row.event, row.payload)}).encode()
    return json.dumps({"event": row.event, "id": row.id, "created_at": row.created_at.isoformat(),
                       "text": text_for(row.event, row.payload), "data": row.payload}, default=str).encode()


def _post(url: str, body: bytes, headers: dict) -> int:
    return httpx.post(url, content=body, headers=headers, timeout=5, follow_redirects=False).status_code


def flush(sessions, allow_private: bool = False, allow_http: bool = False, send: Callable[[str, bytes, dict], int] | None = None,
          now: datetime | None = None, limit: int = 50) -> dict:
    """Deliver due notifications. Network calls happen outside any database transaction."""
    now = now or datetime.now(timezone.utc)
    send = send or _post
    jobs = []
    with sessions.begin() as s:
        due = list(s.execute(select(NotificationRow, NotificationChannelRow)
                             .join(NotificationChannelRow, NotificationChannelRow.id == NotificationRow.channel_id)
                             .where(NotificationRow.status == "pending", NotificationRow.next_attempt_at <= now)
                             .order_by(NotificationRow.created_at).limit(limit)))
        for r, ch in due:
            # Claim with a lease: only the sender whose compare-and-set wins delivers it; if that
            # sender dies, the row becomes due again when the lease runs out.
            won = s.execute(update(NotificationRow).where(NotificationRow.id == r.id, NotificationRow.status == "pending",
                                                          NotificationRow.next_attempt_at == r.next_attempt_at)
                            .values(next_attempt_at=now + timedelta(seconds=LEASE_S))).rowcount == 1
            if won:
                jobs.append((r.id, ch.url, ch.kind, _body(ch, r), ch.signing_secret, r.event))
    results = {}
    for nid, url, kind, body, secret, event in jobs:
        try:
            check_url(url, allow_private, allow_http)
            headers = {"content-type": "application/json", "user-agent": "SentinelOps-Notify/1"}
            if kind == "webhook":
                headers["x-sentinelops-event"] = event
                headers["x-sentinelops-signature"] = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            code = send(url, body, headers)
            results[nid] = (200 <= code < 300, f"HTTP {code}")
        except Unsafe as exc:
            results[nid] = (False, f"refused: {exc}")
        except Exception as exc:  # noqa: BLE001 - a transport error is a failed attempt, retried later
            results[nid] = (False, type(exc).__name__)
    sent = failed = 0
    with sessions.begin() as s:
        for nid, (ok, msg) in results.items():
            r = s.get(NotificationRow, nid)
            r.attempts += 1
            if ok:
                r.status, r.sent_at, r.last_error = "sent", now, ""
                sent += 1
            else:
                r.last_error = msg
                if r.attempts >= MAX_ATTEMPTS or msg.startswith("refused"):
                    r.status = "failed"
                    failed += 1
                else:
                    r.next_attempt_at = now + timedelta(seconds=BACKOFF_S * 2 ** (r.attempts - 1))
    return {"sent": sent, "failed": failed, "retrying": len(results) - sent - failed}


# ---- API ----------------------------------------------------------------------------------------

class NewChannel(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["slack", "webhook"]
    url: str = Field(min_length=8, max_length=2000)
    events: list[str] = Field(default_factory=lambda: sorted(EVENTS))


class ChannelChange(BaseModel):
    enabled: bool | None = None
    events: list[str] | None = None


def register(app: FastAPI, settings, sessions, auth) -> None:
    admin = auth.require("admin")
    allow = dict(allow_private=settings.notify_allow_private, allow_http=settings.notify_allow_private)

    def view(c: NotificationChannelRow) -> dict:
        return {"id": c.id, "name": c.name, "kind": c.kind, "host": urlparse(c.url).hostname, "events": c.events,
                "enabled": c.enabled, "created_by": c.created_by, "created_at": c.created_at.isoformat()}

    def bad_events(events: list[str]) -> list[str]:
        return [e for e in events if e not in EVENTS]

    @app.get("/api/v1/notifications/events")
    def event_types(_p: Annotated[object, Depends(auth.require("read"))]) -> dict:
        return EVENTS

    @app.get("/api/v1/notifications/channels")
    def channels(_p: Annotated[object, Depends(admin)]) -> list[dict]:
        with sessions() as s:
            return [view(c) for c in s.scalars(select(NotificationChannelRow).order_by(NotificationChannelRow.created_at))]

    @app.post("/api/v1/notifications/channels", status_code=201)
    def add_channel(body: NewChannel, p: Annotated[object, Depends(admin)]) -> dict:
        if bad := bad_events(body.events):
            raise HTTPException(status_code=422, detail=f"unknown_events: {bad}")
        try:
            check_url(body.url, **allow)
        except Unsafe as exc:
            raise HTTPException(status_code=422, detail=f"unsafe_url: {exc}") from exc
        secret = secrets.token_hex(24)
        with sessions.begin() as s:
            c = NotificationChannelRow(id=str(uuid.uuid4()), name=body.name, kind=body.kind, url=body.url, signing_secret=secret,
                                       events=sorted(set(body.events)), enabled=True, created_by=p.name,
                                       created_at=datetime.now(timezone.utc))
            s.add(c)
            audit.record(s, p.name, "notification.channel_added", f"{body.name} ({urlparse(body.url).hostname})",
                         {"kind": body.kind, "events": c.events})
            return {**view(c), "signing_secret": secret,
                    "note": "Shown once: generic webhooks carry X-SentinelOps-Signature: sha256=HMAC(secret, body)."}

    @app.patch("/api/v1/notifications/channels/{channel_id}")
    def change_channel(channel_id: str, body: ChannelChange, p: Annotated[object, Depends(admin)]) -> dict:
        with sessions.begin() as s:
            c = s.get(NotificationChannelRow, channel_id)
            if c is None:
                raise HTTPException(status_code=404, detail="not_found")
            if body.events is not None:
                if bad := bad_events(body.events):
                    raise HTTPException(status_code=422, detail=f"unknown_events: {bad}")
                c.events = sorted(set(body.events))
            if body.enabled is not None:
                c.enabled = body.enabled
            audit.record(s, p.name, "notification.channel_changed", c.name, body.model_dump(exclude_none=True))
            return view(c)

    @app.delete("/api/v1/notifications/channels/{channel_id}", status_code=204)
    def delete_channel(channel_id: str, p: Annotated[object, Depends(admin)]) -> None:
        with sessions.begin() as s:
            c = s.get(NotificationChannelRow, channel_id)
            if c is None:
                raise HTTPException(status_code=404, detail="not_found")
            audit.record(s, p.name, "notification.channel_deleted", c.name)
            s.delete(c)

    @app.post("/api/v1/notifications/channels/{channel_id}/test")
    def test_channel(channel_id: str, p: Annotated[object, Depends(admin)]) -> dict:
        with sessions.begin() as s:
            c = s.get(NotificationChannelRow, channel_id)
            if c is None:
                raise HTTPException(status_code=404, detail="not_found")
            now = datetime.now(timezone.utc)
            s.add(NotificationRow(id=str(uuid.uuid4()), channel_id=c.id, event="telemetry.quality", status="pending", attempts=0,
                                  payload={"message": f"Test message requested by {p.name}. Delivery works."},
                                  created_at=now, next_attempt_at=now))
        return flush(sessions, **allow)

    @app.get("/api/v1/notifications")
    def deliveries(_p: Annotated[object, Depends(auth.require("approve"))],
                   limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[dict]:
        with sessions() as s:
            q = (select(NotificationRow, NotificationChannelRow).join(NotificationChannelRow, NotificationChannelRow.id == NotificationRow.channel_id)
                 .order_by(NotificationRow.created_at.desc()).limit(limit))
            return [{"id": r.id, "channel": ch.name, "event": r.event, "status": r.status, "attempts": r.attempts,
                     "last_error": r.last_error, "created_at": r.created_at.isoformat(),
                     "sent_at": r.sent_at.isoformat() if r.sent_at else None, "text": text_for(r.event, r.payload)}
                    for r, ch in s.execute(q)]
