"""Event stream + human-approval plumbing shared by the agent, tools and WebSocket.

Every step the agent takes is published as a flat JSON event so the iOS app can
render a live timeline:

    {"type": "tool_call", "id": "...", "ts": "...", "service": "paypal",
     "tool": "paypal_list_invoices", "title": "...", "detail": "..."}
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

SendFn = Callable[[dict], Awaitable[None]]


class RunContext:
    """Per-run state: how to push events to the client and pending approvals."""

    def __init__(self, send: SendFn, approval_timeout: Optional[float] = None):
        self._send = send
        # The owner may review in the Approvals tab later, so give them time (default 15 min).
        self.approval_timeout = approval_timeout or float(os.getenv("APPROVAL_TIMEOUT_SECONDS", "900"))
        self._pending: dict[str, asyncio.Future[tuple[bool, str]]] = {}
        self.stats = {"tool_calls": 0, "services": set()}
        self.findings: dict[str, list[str]] = {}  # case id -> evidence pinned so far (shown on approvals)
        self.disputes: dict[str, dict] = {}       # case id -> dispute details seen this run
        self.actions: dict[str, list[str]] = {}   # case id -> what Ledger did (goes into the Notion note)
        self.inflight = 0                          # tool calls still running (parallel calls in one step)

    async def emit(
        self,
        type: str,
        title: str,
        detail: Optional[str] = None,
        service: Optional[str] = None,
        tool: Optional[str] = None,
        **extra: Any,
    ) -> dict:
        event = {
            "type": type,
            "id": uuid.uuid4().hex,
            "ts": datetime.now(timezone.utc).isoformat(),
            "title": title,
            "detail": detail,
            "service": service,
            "tool": tool,
        }
        event.update({k: v for k, v in extra.items() if v is not None})
        await self._send(event)
        return event

    # ---- human in the loop -------------------------------------------------
    async def request_approval(
        self, action: str, reason: str, amount: Optional[float] = None, service: Optional[str] = None,
        case: Optional[str] = None, facts: Optional[list[dict]] = None,
    ) -> dict:
        """Pause until the owner decides. Returns {"approved", "note", "expired"}."""
        approval_id = uuid.uuid4().hex
        fut: asyncio.Future[tuple[bool, str]] = asyncio.get_running_loop().create_future()
        self._pending[approval_id] = fut
        await self.emit(
            "approval_request",
            title=action,
            detail=reason,
            service=service,
            approval_id=approval_id,
            amount=amount,
            case=case,
            facts=facts or None,
            evidence=self.findings.get(case or "") or None,
            expires_in=int(self.approval_timeout),
        )
        expired = False
        try:
            approved, note = await asyncio.wait_for(fut, timeout=self.approval_timeout)
        except asyncio.TimeoutError:
            approved, note, expired = False, "", True
        finally:
            self._pending.pop(approval_id, None)
        verdict = "Expired (no answer)" if expired else ("Approved" if approved else "Rejected")
        await self.emit(
            "approval_resolved",
            title=f"{verdict}: {action}",
            detail=note or None,
            service=service,
            approval_id=approval_id,
            approved=approved,
            case=case,
            expired=expired or None,
        )
        return {"approved": approved, "note": note, "expired": expired}

    def resolve_approval(self, approval_id: str, approved: bool, note: str = "") -> bool:
        fut = self._pending.get(approval_id)
        if fut and not fut.done():
            fut.set_result((approved, note.strip()))
            return True
        return False


_current: contextvars.ContextVar[Optional[RunContext]] = contextvars.ContextVar("run_ctx", default=None)


def set_run_context(ctx: RunContext) -> contextvars.Token:
    return _current.set(ctx)


def get_run_context() -> RunContext:
    ctx = _current.get()
    if ctx is None:  # allows tools to be called from scripts/tests without a client
        async def _print(ev: dict) -> None:
            print(json.dumps(ev, default=str))

        ctx = RunContext(_print)
        _current.set(ctx)
    return ctx


def short(value: Any, limit: int = 600) -> str:
    """Compact, human-readable preview of a tool result for the timeline."""
    text = value if isinstance(value, str) else json.dumps(value, default=str, indent=1)
    return text if len(text) <= limit else text[:limit] + " …"
