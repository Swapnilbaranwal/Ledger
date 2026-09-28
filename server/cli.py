"""Terminal client — test the agent without the iOS app.
    python cli.py "Check who owes us money and handle it"
"""
import asyncio, json, sys
import websockets

ICON = {"thought": "💭", "decision": "🧭", "tool_call": "→", "tool_result": "←",
        "approval_request": "✋", "approval_resolved": "✔", "final": "✅", "error": "❌"}

async def main(prompt: str):
    async with websockets.connect("ws://localhost:8000/ws") as ws:
        await ws.send(json.dumps({"type": "run", "prompt": prompt}))
        async for raw in ws:
            ev = json.loads(raw)
            if ev["type"] in ("status", "hello"):
                continue
            print(f"{ICON.get(ev['type'], '•')} [{ev.get('service') or ev['type']}] {ev['title']}")
            if ev.get("detail"):
                print("   " + ev["detail"].replace("\n", "\n   ")[:800])
            if ev["type"] == "approval_request":
                ok = input("   Approve? [y/N] ").strip().lower() == "y"
                await ws.send(json.dumps({"type": "approval", "approval_id": ev["approval_id"], "approved": ok}))
            if ev["type"] == "run_finished":
                break

asyncio.run(main(" ".join(sys.argv[1:]) or "Check who owes us money this month and handle it."))
