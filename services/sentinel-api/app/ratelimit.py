"""Request rate limiting for the SentinelOps API (in memory, per instance).

Keys: the bearer credential (hashed, never stored) or, without one, the client address. Sign-in and
telemetry ingest get their own budgets: sign-in is tight (it is the brute-force target), ingest is
generous (the shop pushes after every request). Over budget means 429 with Retry-After.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import deque

from fastapi import Request
from fastapi.responses import JSONResponse

from .clientaddr import client_address

EXEMPT_PREFIXES = ("/health", "/ui")


class SlidingWindow:
    def __init__(self, max_keys: int = 50_000) -> None:
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def take(self, key: str, limit: int, window_s: float = 60.0) -> tuple[bool, int, float]:
        """(allowed, remaining, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] >= window_s:
                q.popleft()
            if len(q) >= limit:
                return False, 0, max(0.0, window_s - (now - q[0]))
            q.append(now)
            if len(self._hits) > self._max_keys:  # bound memory: forget keys idle for a whole window
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= window_s]:
                    del self._hits[k]
            return True, limit - len(q), 0.0

    def __len__(self) -> int:
        return len(self._hits)


def middleware(settings):
    window = SlidingWindow()

    async def limit(request: Request, call_next):
        path = request.url.path
        if path == "/" or path.startswith(EXEMPT_PREFIXES):
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        addr = client_address(request, settings.trusted_proxy_hops)
        cred = hashlib.sha256(auth.encode()).hexdigest()[:16] if auth else None
        if path == "/api/v1/auth/login":
            kind, budget = "login", settings.login_rate_limit_per_minute
        elif path == "/api/v1/telemetry/events" and request.method == "POST":
            kind, budget = "ingest", settings.ingest_rate_limit_per_minute
        else:
            kind, budget = "api", settings.rate_limit_per_minute
        # Two budgets: per address (so changing the Authorization header buys nothing) and, when a
        # credential is sent, per credential (so one user cannot use up a shared address's budget alone).
        ok, remaining, retry = window.take(f"{kind}|ip|{addr}", budget)
        if ok and cred:
            ok, remaining, retry = window.take(f"{kind}|cred|{cred}", budget)
        if not ok:
            return JSONResponse({"error": "rate_limited", "retry_after_seconds": round(retry, 1)}, status_code=429,
                                headers={"Retry-After": str(max(1, int(retry + 0.999))), "X-RateLimit-Limit": str(budget),
                                         "X-RateLimit-Remaining": "0"})
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(budget)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
    return limit
