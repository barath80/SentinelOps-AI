"""Action executors. The MVP only ever touches mock or sandbox/demo resources.

An executor reports whether the *action* ran. It says nothing about whether the system
recovered: that is decided separately by the SLO verifier from telemetry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import httpx


@dataclass
class ActionResult:
    ok: bool
    output: dict = field(default_factory=dict)


class Executor(Protocol):
    name: str

    def capture(self, action_id: str, environment: str, timeout_seconds: int) -> ActionResult:
        """Read (never change) the state the action will alter, so it can be restored later."""
        ...

    def run(self, action_id: str, environment: str, timeout_seconds: int) -> ActionResult: ...

    def revert(self, action_id: str, environment: str, snapshot: dict, timeout_seconds: int) -> ActionResult:
        """Put back the state recorded by capture() before `action_id` ran."""
        ...


class MockExecutor:
    """Records the call and does nothing else. The default: safe everywhere."""

    name = "mock"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def capture(self, action_id: str, environment: str, timeout_seconds: int) -> ActionResult:
        return ActionResult(True, {"simulated": True, "action": action_id})

    def run(self, action_id: str, environment: str, timeout_seconds: int) -> ActionResult:
        self.calls.append((action_id, environment))
        return ActionResult(True, {"simulated": True, "action": action_id, "environment": environment})

    def revert(self, action_id: str, environment: str, snapshot: dict, timeout_seconds: int) -> ActionResult:
        self.calls.append((f"revert:{action_id}", environment))
        return ActionResult(True, {"simulated": True, "reverted": action_id, "restored": snapshot})


# In the demo shop every fault is a toggle, so each "fix" is switching the fault scenario off.
_SHOP_ACTIONS = {"rollback_release", "restore_payment_simulator", "apply_query_fix", "recycle_db_pool",
                 "restore_cache", "scale_out", "enable_retry_backoff"}


class ShopAdminExecutor:
    """Calls the demo shop's token-protected /api/admin/fault endpoint. Demo/sandbox only."""

    name = "shop_admin"

    def __init__(self, base_url: str, admin_token: str) -> None:
        if not base_url or not admin_token:
            raise ValueError("shop_admin executor needs SENTINEL_SHOP_ADMIN_URL and SENTINEL_SHOP_ADMIN_TOKEN")
        self.base_url = base_url.rstrip("/")
        self.admin_token = admin_token

    def _set(self, scenario: str, timeout_seconds: int) -> ActionResult:
        try:
            res = httpx.post(f"{self.base_url}/api/admin/fault", json={"scenario": scenario},
                             headers={"x-admin-token": self.admin_token}, timeout=timeout_seconds)
        except httpx.HTTPError as exc:
            return ActionResult(False, {"error": type(exc).__name__})
        ok = res.status_code == 200 and res.json().get("active") == scenario
        return ActionResult(ok, {"status_code": res.status_code, "response": res.json() if ok else None})

    def capture(self, action_id: str, environment: str, timeout_seconds: int) -> ActionResult:
        if action_id not in _SHOP_ACTIONS:
            return ActionResult(False, {"error": f"executor has no implementation for {action_id}"})
        try:
            res = httpx.get(f"{self.base_url}/api/admin/fault", headers={"x-admin-token": self.admin_token},
                            timeout=timeout_seconds)
        except httpx.HTTPError as exc:
            return ActionResult(False, {"error": type(exc).__name__})
        active = res.json().get("active") if res.status_code == 200 else None
        if not isinstance(active, str):
            return ActionResult(False, {"status_code": res.status_code, "error": "could not read the active scenario"})
        return ActionResult(True, {"scenario": active})

    def run(self, action_id: str, environment: str, timeout_seconds: int) -> ActionResult:
        if action_id not in _SHOP_ACTIONS:
            return ActionResult(False, {"error": f"executor has no implementation for {action_id}"})
        return self._set("none", timeout_seconds)

    def revert(self, action_id: str, environment: str, snapshot: dict, timeout_seconds: int) -> ActionResult:
        # Restoring the captured scenario can re-activate the original fault. That is what a rollback
        # means here: the change did not help (or made things worse), so the system goes back to
        # exactly where it was before, and the incident stays open.
        scenario = snapshot.get("scenario")
        if action_id not in _SHOP_ACTIONS or not isinstance(scenario, str):
            return ActionResult(False, {"error": "no restorable snapshot for this action"})
        return self._set(scenario, timeout_seconds)
