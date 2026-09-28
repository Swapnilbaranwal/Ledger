"""In-memory backends that behave like the real services (rehearsals + stage fallback)."""
from __future__ import annotations

import asyncio
import random
from datetime import date

from ..seed import fresh_state

STATE: dict = fresh_state()
MTD_BEFORE_WINDOW = 9820.0  # month-to-date revenue earlier than the 7-day window


def reset() -> None:
    STATE.clear()
    STATE.update(fresh_state())


async def _latency() -> None:
    await asyncio.sleep(random.uniform(0.25, 0.6))


def _terms(query: str) -> list[str]:
    return [t.strip().lower() for t in query.replace(",", " ").split() if t.strip()]


class MockPayPal:
    async def sales_summary(self, days: int = 7) -> dict:
        await _latency()
        today = date.today()
        txs = [t for t in STATE["transactions"] if (today - date.fromisoformat(t["date"])).days < days]
        by_day: dict[str, float] = {}
        for t in txs:
            by_day[t["date"]] = by_day.get(t["date"], 0) + t["amount"]
        gross = sum(t["amount"] for t in txs)
        return {"days": days, "currency": "USD", "gross": gross, "orders": len(txs),
                "today": by_day.get(today.isoformat(), 0.0), "by_day": by_day,
                "month_to_date": gross + MTD_BEFORE_WINDOW, "transactions": txs}

    async def list_disputes(self) -> list[dict]:
        await _latency()
        return [{k: d[k] for k in ("dispute_id", "reason", "status", "amount", "currency", "buyer", "filed", "respond_by")}
                for d in STATE["disputes"] if d["status"] == "OPEN"]

    async def get_dispute(self, dispute_id: str) -> dict:
        await _latency()
        d = next((d for d in STATE["disputes"] if d["dispute_id"] == dispute_id), None)
        return dict(d) if d else {"ok": False, "error": f"Dispute {dispute_id} not found"}

    def _set_status(self, dispute_id: str, status: str) -> bool:
        for d in STATE["disputes"]:
            if d["dispute_id"] == dispute_id:
                d["status"] = status
                return True
        return False

    async def provide_evidence(self, dispute_id: str, summary: str, evidence: list[str]) -> dict:
        await _latency()
        if not self._set_status(dispute_id, "UNDER_REVIEW"):
            return {"ok": False, "error": f"Dispute {dispute_id} not found"}
        STATE["evidence"].append({"dispute_id": dispute_id, "summary": summary, "evidence": evidence})
        return {"ok": True, "dispute_id": dispute_id, "status": "UNDER_REVIEW", "evidence_items": len(evidence)}

    async def make_offer(self, dispute_id: str, amount: float, note: str) -> dict:
        await _latency()
        if not self._set_status(dispute_id, "WAITING_FOR_BUYER_RESPONSE"):
            return {"ok": False, "error": f"Dispute {dispute_id} not found"}
        STATE["offers"].append({"dispute_id": dispute_id, "amount": amount, "note": note})
        return {"ok": True, "dispute_id": dispute_id, "offer_amount": amount, "status": "WAITING_FOR_BUYER_RESPONSE"}

    async def accept_claim(self, dispute_id: str, note: str) -> dict:
        await _latency()
        if not self._set_status(dispute_id, "RESOLVED"):
            return {"ok": False, "error": f"Dispute {dispute_id} not found"}
        STATE["accepted"].append({"dispute_id": dispute_id, "note": note})
        return {"ok": True, "dispute_id": dispute_id, "status": "RESOLVED", "outcome": "REFUNDED_TO_BUYER"}


class MockGmail:
    async def search(self, query: str) -> list[dict]:
        await _latency()
        terms = _terms(query)
        hits = []
        for m in STATE["inbox"]:
            hay = f"{m['from']} {m['subject']} {m['body']}".lower()
            if any(t.removeprefix("from:") in hay for t in terms):
                hits.append(m)
        return hits[:10]

    async def send_email(self, to: str, subject: str, body: str) -> dict:
        await _latency()
        STATE["outbox"].append({"to": to, "subject": subject, "body": body})
        return {"ok": True, "message_id": f"sent-{len(STATE['outbox'])}"}


class MockNotion:
    async def get_playbook(self) -> str:
        await _latency()
        return STATE["playbook"]

    async def find_orders(self, query: str) -> list[dict]:
        await _latency()
        terms = _terms(query)
        return [o for o in STATE["orders"]
                if any(t in f"{o['order_id']} {o['customer']} {o['email']}".lower() for t in terms)]

    async def log_case(self, title: str, verdict: str, summary: str) -> dict:
        await _latency()
        page_id = f"mock-case-{len(STATE['cases']) + 1}"
        STATE["cases"].append({"id": page_id, "title": title, "verdict": verdict, "summary": summary})
        return {"ok": True, "id": page_id, "page": f"Case File #{len(STATE['cases'])}: {title}"}

    async def find_case(self, case: str) -> dict | None:
        c = next((c for c in STATE["cases"] if c["title"].startswith(case)), None)
        return {"id": c["id"], "page": c["title"]} if c else None

    async def append_case(self, existing: dict, markdown: str) -> dict:
        await _latency()
        for c in STATE["cases"]:
            if c["id"] == existing.get("id"):
                c["summary"] += "\n\n" + markdown
                return {"ok": True, "page": c["title"]}
        return {"ok": False, "error": "Case note not found"}


class MockJira:
    async def list_open(self) -> list[dict]:
        await _latency()
        return [i for i in STATE["jira"] if i["status"] != "Done"]

    async def find(self, text: str) -> list[dict]:
        return [dict(t) for t in STATE["jira"] if text.lower() in t["summary"].lower()]

    async def create_issue(self, summary: str, description: str, priority: str) -> dict:
        await _latency()
        key = f"OPS-{20 + len(STATE['jira'])}"
        STATE["jira"].append({"key": key, "summary": summary, "description": description,
                              "priority": priority, "status": "To Do", "assignee": "@priya"})
        return {"ok": True, "key": key}


class MockSlack:
    async def post_message(self, channel: str, text: str) -> dict:
        await _latency()
        STATE["slack"].append({"channel": channel, "text": text})
        return {"ok": True, "channel": channel}
