"""Ledger's work log: what was already done for each dispute, and the recent conversation.

Kept in a JSON file so it survives server restarts and phone reconnects. The agent reads it at the
start of every request (so follow-ups like "share the results on Slack" don't redo the work), and
the tools consult it to refuse duplicates (a second Jira ticket, Notion note, refund or email).

    LEDGER_MEMORY_PATH=data/ledger_memory.json   (default, relative to server/)
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_TURNS = 6


def _path() -> str:
    p = os.getenv("LEDGER_MEMORY_PATH", "data/ledger_memory.json")
    return p if os.path.isabs(p) else os.path.join(SERVER_DIR, p)


def _now() -> str:
    return datetime.now().isoformat(timespec="minutes")


def load() -> dict:
    try:
        with open(_path()) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data.setdefault("cases", {})
    data.setdefault("turns", [])
    data.setdefault("emails", [])  # every email sent, even if it couldn't be tied to a case
    return data


def save(data: dict) -> None:
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    tmp = _path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, _path())


def reset() -> None:
    save({"cases": {}, "turns": [], "emails": []})


def case(case_id: str) -> dict:
    return load()["cases"].get(case_id, {})


def record(case_id: str | None, kind: str, **item: Any) -> None:
    """Append one thing Ledger did for a case: kind is jira | notion | email | paypal | decision."""
    if not case_id:
        return
    data = load()
    c = data["cases"].setdefault(case_id, {})
    c.setdefault(kind, []).append({**item, "at": _now()})
    c["updated"] = _now()
    save(data)


def update(case_id: str | None, **fields: Any) -> None:
    """Set case-level fields such as buyer or verdict."""
    if not case_id:
        return
    data = load()
    c = data["cases"].setdefault(case_id, {})
    c.update({k: v for k, v in fields.items() if v})
    c["updated"] = _now()
    save(data)


def set_note(case_id: str, **note: Any) -> None:
    data = load()
    data["cases"].setdefault(case_id, {})["notion"] = [{**note, "at": _now()}]
    save(data)


def add_turn(prompt: str, answer: str) -> None:
    data = load()
    data["turns"] = (data["turns"] + [{"prompt": prompt, "answer": answer, "at": _now()}])[-MAX_TURNS:]
    save(data)


# ---------------------------------------------------------------- duplicate checks
def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower().replace("pp-d-", "ppd")) if len(w) > 2}


def similar(a: str, b: str) -> bool:
    """Same purpose? e.g. "PP-D-7002 · Buyer to accept offer" vs "PP-D-7002 · buyer accept $72 offer"."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= 0.5 or wa <= wb or wb <= wa


FIX_WORDS = {"stop", "shipment", "restock", "qc", "quality", "fix", "block", "warehouse", "process", "cancel"}


def match_ticket(summary: str, tickets: list[dict]) -> dict | None:
    """One tracking ticket per dispute, plus one per distinct fix. Returns the ticket that already
    covers `summary`, if any."""
    for t in tickets:
        if similar(t.get("summary", ""), summary):
            return t
    fix = _words(summary) & FIX_WORDS
    for t in tickets:
        their_fix = _words(t.get("summary", "")) & FIX_WORDS
        if (fix and fix & their_fix) or (not fix and not their_fix):
            return t
    return None


def find_ticket(case_id: str, summary: str) -> dict | None:
    return match_ticket(summary, case(case_id).get("jira", []))


def done_money(case_id: str) -> dict | None:
    """An approved refund/offer already went through for this case."""
    for p in case(case_id).get("paypal", []):
        if p.get("action") in ("offer", "refund") and p.get("approved"):
            return p
    return None


def contested(case_id: str) -> dict | None:
    return next((p for p in case(case_id).get("paypal", []) if p.get("action") == "evidence"), None)


def record_email(case_id: str | None, to: str, subject: str) -> None:
    data = load()
    data["emails"].append({"to": to, "subject": subject, "case": case_id, "at": _now()})
    save(data)
    record(case_id, "email", to=to, subject=subject)


def sent_email(to: str, subject: str) -> dict | None:
    for e in load()["emails"]:
        if e.get("to", "").lower() == to.lower() and similar(e.get("subject", ""), subject):
            return e
    return None


# ---------------------------------------------------------------- what the agent sees
def summary() -> str:
    """Compact work log for the system prompt: one block per case, links included."""
    data = load()
    lines = []
    for cid, c in sorted(data["cases"].items()):
        head = f"- {cid}"
        if c.get("verdict"):
            head += f" [{c['verdict']}]"
        if c.get("buyer"):
            head += f" {c['buyer']}"
        lines.append(head + f" (last update {c.get('updated', '?')})")
        for p in c.get("paypal", []):
            lines.append(f"    PayPal: {p.get('text')}")
        for t in c.get("jira", []):
            lines.append(f"    Jira {t.get('key')}: {t.get('summary')} {t.get('url') or ''}".rstrip())
        for n in c.get("notion", []):
            lines.append(f"    Notion note ({n.get('folder', '')}): {n.get('url') or n.get('page') or ''}")
        for e in c.get("email", []):
            lines.append(f"    Email to {e.get('to')}: \"{e.get('subject')}\"")
    turns = [f"- Owner: {t['prompt']}\n  Ledger: {t['answer']}" for t in data["turns"]]
    out = []
    if lines:
        out.append("WORK ALREADY DONE (from Ledger's work log; do not redo it):\n" + "\n".join(lines))
    if turns:
        out.append("RECENT CONVERSATION (oldest first):\n" + "\n".join(turns))
    return "\n\n".join(out) or "WORK ALREADY DONE: nothing yet."


def status_of(case_id: str) -> str | None:
    """One line for paypal_list_disputes, so the agent sees which disputes are already handled."""
    c = case(case_id)
    if not c:
        return None
    bits = []
    if c.get("verdict"):
        bits.append(c["verdict"])
    if c.get("jira"):
        bits.append("Jira " + ", ".join(t.get("key", "?") for t in c["jira"]))
    if c.get("notion"):
        bits.append("Notion note exists")
    if c.get("email"):
        bits.append(f"{len(c['email'])} email(s) sent")
    return "ALREADY HANDLED by Ledger: " + "; ".join(bits) if bits else None
