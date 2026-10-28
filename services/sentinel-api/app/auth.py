"""Operator authentication and role-based permissions.

Two credentials exist:
  * Operator sessions: a person logs in (POST /api/v1/auth/login) and receives a signed session
    token. Every request re-reads the operator from the database, so disabling an account, a
    password change or logging out revokes its sessions at once, and the role used is always the
    current one, never the one written into the token.
  * The machine token (SENTINEL_INGEST_TOKEN): for the shop's telemetry push and automation. It
    may ingest, read and run the read-only analysis, but never act as a person: it cannot label,
    propose, approve, execute or roll back anything.

`auth_mode = "shared_token"` keeps the old behaviour (one token, identity asserted in X-Actor)
for local development and tests only: anyone holding the token can claim any name.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from .config import Settings
from .db import OperatorRow

ROLES = ("viewer", "responder", "approver", "admin")
# permission -> lowest role that has it. "machine" marks what the machine token may also do.
PERMISSIONS = {
    "read": ("viewer", True),
    "analyze": ("responder", True),  # detection, diagnostics, investigation: read-only analysis
    "ingest": ("admin", True),
    "act": ("responder", False),  # label, propose, rehearse, execute, verify, roll back, generate prevention
    "approve": ("approver", False),  # approve contracts, review prevention artifacts
    "admin": ("admin", False),  # operators, retention purge
}
USERNAME = re.compile(r"^[a-z0-9_.@-]{2,100}$")
MIN_PASSWORD = 12
MAX_FAILURES, LOCKOUT_SECONDS = 5, 900
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


@dataclass(frozen=True)
class Principal:
    kind: str  # operator | machine | shared
    name: str
    role: str  # a ROLES entry, or "machine"


# ---- passwords and tokens ---------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return "scrypt${n}${r}${p}${salt}${digest}".format(**_SCRYPT, salt=base64.b64encode(salt).decode(),
                                                      digest=base64.b64encode(digest).decode())


def check_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), dklen=32, n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(got, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))  # equalizes timing for unknown usernames


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(secret: str, claims: dict) -> str:
    body = _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    mac = hmac.new(secret.encode(), f"s1.{body}".encode(), hashlib.sha256).digest()
    return f"s1.{body}.{_b64(mac)}"


def verify(secret: str, token: str) -> dict | None:
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "s1" or not secret:
        return None
    mac = hmac.new(secret.encode(), f"s1.{parts[1]}".encode(), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(mac, _unb64(parts[2])):
            return None
        claims = json.loads(_unb64(parts[1]))
    except (ValueError, TypeError):
        return None
    return claims if isinstance(claims, dict) and claims.get("exp", 0) > time.time() else None


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class _Lockout:
    """Failed logins per username, in memory (per instance): 5 failures lock it for 15 minutes."""

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def locked(self, key: str) -> bool:
        with self._lock:
            recent = [t for t in self._failures.get(key, []) if time.time() - t < LOCKOUT_SECONDS]
            self._failures[key] = recent
            return len(recent) >= MAX_FAILURES

    def fail(self, key: str) -> None:
        with self._lock:
            self._failures.setdefault(key, []).append(time.time())

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


# ---- request models ---------------------------------------------------------------------------

class Login(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=200)


class NewOperator(BaseModel):
    username: str = Field(pattern=USERNAME.pattern)
    password: str = Field(min_length=MIN_PASSWORD, max_length=200)
    role: str = Field(pattern="^(viewer|responder|approver|admin)$")


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(min_length=MIN_PASSWORD, max_length=200)


class RoleChange(BaseModel):
    role: str | None = Field(default=None, pattern="^(viewer|responder|approver|admin)$")
    disabled: bool | None = None


def create_operator(session, username: str, password: str, role: str, created_by: str) -> OperatorRow:
    if not USERNAME.match(username) or role not in ROLES or len(password) < MIN_PASSWORD:
        raise ValueError("invalid operator")
    now = datetime.now(timezone.utc)
    row = OperatorRow(username=username, password_hash=hash_password(password), role=role, disabled=False,
                      created_by=created_by, created_at=now, sessions_valid_after=now)
    session.add(row)
    return row


def bootstrap(sessions, settings: Settings) -> None:
    """Create the first admin from SENTINEL_BOOTSTRAP_ADMIN ("username:password") if no operator exists."""
    if not settings.bootstrap_admin or ":" not in settings.bootstrap_admin:
        return
    username, password = settings.bootstrap_admin.split(":", 1)
    with sessions.begin() as s:
        if s.scalar(select(OperatorRow.username).limit(1)) is None:
            create_operator(s, username.strip().lower(), password, "admin", "bootstrap")


# ---- FastAPI wiring ---------------------------------------------------------------------------

class InsecureModeRefused(RuntimeError):
    pass


def check_mode(settings: Settings, environ=None) -> None:
    """shared_token mode is for development only: refuse to start it anywhere else."""
    import os
    environ = os.environ if environ is None else environ
    if settings.auth_mode != "shared_token":
        return
    if not settings.allow_insecure_shared_token:
        raise InsecureModeRefused("SENTINEL_AUTH_MODE=shared_token needs SENTINEL_ALLOW_INSECURE_SHARED_TOKEN=true "
                                  "(development only: anyone with the token can claim any identity)")
    if environ.get("RENDER") or environ.get("VERCEL"):
        raise InsecureModeRefused("shared_token mode is refused on a hosted deployment; use operators")


class Auth:
    def __init__(self, settings: Settings, sessions):
        check_mode(settings)
        self.settings, self.sessions, self.lockout = settings, sessions, _Lockout()

    @property
    def operators_mode(self) -> bool:
        return self.settings.auth_mode == "operators"

    def _machine(self, supplied: str) -> bool:
        expected = self.settings.ingest_token
        return bool(expected) and hmac.compare_digest(supplied, expected)

    def principal(self, authorization: str | None, x_actor: str | None) -> Principal:
        supplied = (authorization or "").removeprefix("Bearer ").strip()
        if not self.operators_mode:
            if not self._machine(supplied):
                raise HTTPException(status_code=401, detail="invalid_token")
            return Principal("shared", x_actor or "", "admin")
        if self._machine(supplied):
            return Principal("machine", "machine", "machine")
        claims = verify(self.settings.session_secret, supplied) if supplied.startswith("s1.") else None
        if not claims:
            raise HTTPException(status_code=401, detail="invalid_token")
        with self.sessions() as s:
            op = s.get(OperatorRow, claims.get("sub", ""))
        valid_after = _aware(op.sessions_valid_after) if op else None
        if op is None or op.disabled or (valid_after and claims.get("iat", 0) < valid_after.timestamp()):
            raise HTTPException(status_code=401, detail="session_revoked")
        return Principal("operator", op.username, op.role)

    def require(self, permission: str):
        lowest, machine_ok = PERMISSIONS[permission]

        def dep(authorization: Annotated[str | None, Header()] = None,
                x_actor: Annotated[str | None, Header()] = None) -> Principal:
            p = self.principal(authorization, x_actor)
            if p.kind == "shared":
                return p
            if p.kind == "machine":
                if not machine_ok:
                    raise HTTPException(status_code=403, detail="operator_login_required")
                return p
            if ROLES.index(p.role) < ROLES.index(lowest):
                raise HTTPException(status_code=403, detail=f"role_{lowest}_required")
            return p
        return dep

    def actor(self, permission: str):
        """A dependency giving the acting person's name for the audit trail."""
        need = self.require(permission)

        def dep(p: Annotated[Principal, Depends(need)]) -> str:
            if p.kind == "shared":  # legacy: identity is only asserted by the caller
                if not p.name or not re.match(r"^[A-Za-z0-9_.@-]{1,100}$", p.name):
                    raise HTTPException(status_code=400, detail="x_actor_header_required")
            return p.name
        return dep

    def register(self, app: FastAPI) -> None:
        settings, sessions = self.settings, self.sessions

        @app.get("/api/v1/auth/mode")
        def mode() -> dict:
            return {"mode": settings.auth_mode, "login_configured": bool(settings.session_secret)}

        @app.post("/api/v1/auth/login")
        def login(body: Login, request: Request) -> dict:
            if not self.operators_mode:
                raise HTTPException(status_code=404, detail="operator_auth_disabled")
            if not settings.session_secret:
                raise HTTPException(status_code=503, detail="session_secret_not_configured")
            username = body.username.strip().lower()
            if self.lockout.locked(username):
                raise HTTPException(status_code=429, detail="too_many_failed_logins")
            with sessions.begin() as s:
                op = s.get(OperatorRow, username)
                ok = check_password(body.password, op.password_hash if op else _DUMMY_HASH) and op is not None and not op.disabled
                if not ok:
                    self.lockout.fail(username)
                    raise HTTPException(status_code=401, detail="invalid_credentials")
                self.lockout.clear(username)
                op.last_login_at = datetime.now(timezone.utc)
                role = op.role
            now = time.time()
            # iat is kept to the microsecond so a session issued just after a revocation stays valid
            claims = {"sub": username, "iat": now, "exp": now + settings.session_ttl_seconds, "sid": secrets.token_hex(8)}
            return {"token": sign(settings.session_secret, claims), "username": username, "role": role,
                    "expires_at": datetime.fromtimestamp(claims["exp"], tz=timezone.utc).isoformat()}

        @app.get("/api/v1/auth/me")
        def me(p: Annotated[Principal, Depends(self.require("read"))]) -> dict:
            return {"kind": p.kind, "username": p.name, "role": p.role, "mode": settings.auth_mode}

        @app.post("/api/v1/auth/logout")
        def logout(p: Annotated[Principal, Depends(self.require("read"))]) -> dict:
            """Ends every session of this operator (all devices)."""
            if p.kind == "operator":
                with sessions.begin() as s:
                    s.get(OperatorRow, p.name).sessions_valid_after = datetime.now(timezone.utc)
            return {"logged_out": p.kind == "operator"}

        @app.post("/api/v1/auth/password")
        def change_password(body: PasswordChange, p: Annotated[Principal, Depends(self.require("read"))]) -> dict:
            if p.kind != "operator":
                raise HTTPException(status_code=403, detail="operator_login_required")
            with sessions.begin() as s:
                op = s.get(OperatorRow, p.name)
                if not check_password(body.current_password, op.password_hash):
                    raise HTTPException(status_code=401, detail="invalid_credentials")
                op.password_hash = hash_password(body.new_password)
                op.sessions_valid_after = datetime.now(timezone.utc)  # log out everywhere
            return {"changed": True, "hint": "log in again"}

        admin = self.require("admin")

        def view(op: OperatorRow) -> dict:
            return {"username": op.username, "role": op.role, "disabled": op.disabled, "created_by": op.created_by,
                    "created_at": op.created_at.isoformat(),
                    "last_login_at": op.last_login_at.isoformat() if op.last_login_at else None}

        @app.get("/api/v1/operators")
        def list_operators(_p: Annotated[Principal, Depends(admin)]) -> list[dict]:
            with sessions() as s:
                return [view(o) for o in s.scalars(select(OperatorRow).order_by(OperatorRow.username))]

        @app.post("/api/v1/operators", status_code=201)
        def add_operator(body: NewOperator, p: Annotated[Principal, Depends(admin)]) -> dict:
            with sessions.begin() as s:
                if s.get(OperatorRow, body.username):
                    raise HTTPException(status_code=409, detail="operator_exists")
                return view(create_operator(s, body.username, body.password, body.role, p.name or "admin"))

        @app.patch("/api/v1/operators/{username}")
        def change_operator(username: str, body: RoleChange, p: Annotated[Principal, Depends(admin)]) -> dict:
            with sessions.begin() as s:
                op = s.get(OperatorRow, username)
                if op is None:
                    raise HTTPException(status_code=404, detail="not_found")
                if username == p.name and (body.disabled or (body.role and body.role != "admin")):
                    raise HTTPException(status_code=409, detail="cannot_demote_or_disable_yourself")
                if body.role:
                    op.role = body.role
                if body.disabled is not None:
                    op.disabled = body.disabled
                    if body.disabled:
                        op.sessions_valid_after = datetime.now(timezone.utc)
                return view(op)
