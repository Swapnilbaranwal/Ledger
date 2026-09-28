"""FastAPI server: WebSocket stream for the iOS app + demo helpers.

Client → server messages:
    {"type": "run", "prompt": "..."}
    {"type": "approval", "approval_id": "...", "approved": true, "note": "optional reason"}
    {"type": "cancel"}
Server → client: flat events (see events.py).
"""
from __future__ import annotations

import asyncio
import logging

from dotenv import load_dotenv

load_dotenv()

from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect  # noqa: E402

from . import backends, memory  # noqa: E402
from .agent import build_graph, run_agent  # noqa: E402
from .backends import mock  # noqa: E402
from .events import RunContext, set_run_context  # noqa: E402

log = logging.getLogger("ledger")
app = FastAPI(title="Ledger agent")
_graph = None


def graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


@app.get("/health")
async def health():
    return {"ok": True, "backends": backends.describe()}


# ---------------------------------------------------------------- demo helpers (mock mode)
@app.post("/demo/reset")
async def demo_reset():
    mock.reset()
    return {"ok": True}


@app.get("/memory")
async def get_memory():
    """What Ledger remembers doing (work log) and the recent conversation."""
    return memory.load()


@app.post("/memory/reset")
async def reset_memory():
    """Forget all past work, e.g. after deleting the test tickets and notes."""
    memory.reset()
    return {"ok": True}


@app.get("/demo/state")
async def demo_state():
    s = mock.STATE
    return {k: s[k] for k in ("disputes", "evidence", "offers", "accepted", "cases", "outbox", "slack", "jira")}


@app.get("/demo/playbook")
async def get_playbook():
    return {"playbook": mock.STATE["playbook"]}


@app.put("/demo/playbook")
async def put_playbook(playbook: str = Body(..., embed=True)):
    """Demo trick: change a rule live on stage (e.g. max partial refund 40% -> 20%) and re-run."""
    mock.STATE["playbook"] = playbook
    return {"ok": True}


# ---------------------------------------------------------------- websocket
@app.websocket("/ws")
async def ws(websocket: WebSocket):
    print(f"[ledger ws] incoming connection from {websocket.client}", flush=True)
    await websocket.accept()
    print("[ledger ws] accepted", flush=True)
    send_lock = asyncio.Lock()

    async def send(event: dict):
        async with send_lock:
            await websocket.send_json(event)

    ctx = RunContext(send)
    task: asyncio.Task | None = None

    async def run(prompt: str):
        set_run_context(ctx)
        ctx.stats = {"tool_calls": 0, "services": set()}
        ctx.findings, ctx.disputes, ctx.actions = {}, {}, {}  # per request; the work log keeps history
        try:
            await run_agent(graph(), prompt)
        except asyncio.CancelledError:
            await ctx.emit("error", title="Run cancelled")
        except Exception as e:  # show errors in the app instead of dropping the socket
            log.exception("run failed")
            await ctx.emit("error", title="Agent error", detail=f"{type(e).__name__}: {e}")
        finally:
            await ctx.emit("run_finished", title="Finished")

    try:
        await ctx.emit("hello", title="Connected to Ledger", detail=str(backends.describe()))
        print("[ledger ws] hello sent", flush=True)
    except Exception as e:
        print(f"[ledger ws] FAILED to send hello: {type(e).__name__}: {e}", flush=True)
        raise
    try:
        while True:
            msg = await websocket.receive_json()
            print(f"[ledger ws] received: {msg}", flush=True)
            kind = msg.get("type")
            if kind == "run":
                if task and not task.done():
                    await ctx.emit("error", title="A run is already in progress")
                    continue
                task = asyncio.create_task(run(msg.get("prompt", "").strip() or "Handle overdue invoices."))
            elif kind == "approval":
                ctx.resolve_approval(msg.get("approval_id", ""), bool(msg.get("approved")), str(msg.get("note") or ""))
            elif kind == "cancel" and task:
                task.cancel()
    except WebSocketDisconnect as e:
        print(f"[ledger ws] client disconnected (code={e.code})", flush=True)
        if task and not task.done():
            task.cancel()
