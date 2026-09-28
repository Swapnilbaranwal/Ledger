"""End-to-end test without an LLM key: a scripted model drives the real graph,
real tools and mock backends over the real WebSocket.  Run:  python -m pytest -q"""
from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app import main
from app.agent import build_graph
from app.backends import mock


def call(name: str, i: int, **args) -> dict:
    return {"name": name, "args": args, "id": f"call_{name}_{i}", "type": "tool_call"}


SCRIPT = [
    AIMessage("Reading the playbook and pulling disputes.",
              tool_calls=[call("notion_get_playbook", 1), call("paypal_sales_summary", 2, days=7),
                          call("paypal_list_disputes", 3), call("jira_list_open_issues", 4)]),
    AIMessage("Investigating PP-D-7001 (not received).",
              tool_calls=[call("paypal_get_dispute", 5, dispute_id="PP-D-7001"),
                          call("notion_find_orders", 6, query="KC-1042"),
                          call("gmail_search", 7, query="john.carter@example.com")]),
    AIMessage("Delivery signed and buyer praised the lamp: contest.",
              tool_calls=[call("record_finding", 8, case="PP-D-7001", finding="Buyer emailed 'lamp arrived'", points_to="merchant"),
                          call("paypal_provide_evidence", 9, dispute_id="PP-D-7001", summary="Delivered and confirmed",
                               evidence=["DHL signed by J CARTER", "Buyer email confirming receipt"])]),
    AIMessage("PP-D-7002 is our fault: offer 40%.",
              tool_calls=[call("paypal_make_offer", 10, dispute_id="PP-D-7002", amount=72.0, note="Sorry, wrong colour"),
                          call("gmail_send_email", 11, to="emma.liu@example.co.uk", subject="Sorry", body="Apologies")]),
    AIMessage("PP-D-7003 is fraud: accept, stop shipment, alert.",
              tool_calls=[call("paypal_accept_claim", 12, dispute_id="PP-D-7003", amount=1250.0, note="Fraud pattern"),
                          call("jira_create_issue", 13, summary="Stop KC-1062 shipment", description="Fraud", priority="High"),
                          call("notion_log_case", 14, title="PP-D-7003", verdict="ACCEPTED_FRAUD", summary="...")]),
    AIMessage("", tool_calls=[call("slack_post_message", 15, channel="#ops", text="3 disputes handled")]),
    AIMessage("Contested 420 dollars, offered 72 to Emma, refunded the 1,250 fraud claim and stopped the last shipment."),
]


class ScriptedModel(BaseChatModel):
    step: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kw: Any):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kw) -> ChatResult:
        msg = SCRIPT[min(self.step, len(SCRIPT) - 1)]
        self.step += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _run(decide):
    mock.reset()
    return _run_keep_state(decide)


def _run_keep_state(decide):
    main._graph = build_graph(ScriptedModel())
    client = TestClient(main.app)
    events = []
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "run", "prompt": "Investigate the disputes"})
        while True:
            ev = ws.receive_json()
            events.append(ev)
            if ev["type"] == "approval_request":
                d = decide(ev)
                approved, note = d if isinstance(d, tuple) else (d, "")
                ws.send_json({"type": "approval", "approval_id": ev["approval_id"], "approved": approved, "note": note})
            if ev["type"] == "run_finished":
                return events


def test_detective_run_with_approvals():
    events = _run(lambda ev: True)
    types = [e["type"] for e in events]
    assert "error" not in types, [e for e in events if e["type"] == "error"]
    assert types.count("approval_request") == 2 and "final" in types and "finding" in types
    final = next(e for e in events if e["type"] == "final")
    assert {"paypal", "notion", "gmail", "jira", "slack"} <= set(final["services"])
    st = {d["dispute_id"]: d["status"] for d in mock.STATE["disputes"]}
    assert st == {"PP-D-7001": "UNDER_REVIEW", "PP-D-7002": "WAITING_FOR_BUYER_RESPONSE", "PP-D-7003": "RESOLVED"}


def test_rejected_money_actions_move_nothing():
    _run(lambda ev: False)
    assert mock.STATE["offers"] == [] and mock.STATE["accepted"] == []
    assert mock.STATE["evidence"]  # contesting needs no approval


def test_gmail_and_notion_mock_search():
    import asyncio
    from app.backends.mock import MockGmail, MockNotion
    mock.reset()
    assert asyncio.run(MockGmail().search("john.carter@example.com"))[0]["id"] == "m1"
    assert len(asyncio.run(MockNotion().find_orders("alex.m.buys@example.net"))) == 3


def test_approval_shows_context_and_carries_rejection_reason():
    events = _run(lambda ev: (False, "Too high, offer 20% instead"))
    req = next(e for e in events if e["type"] == "approval_request")
    facts = {f["label"]: f["value"] for f in req["facts"]}
    assert req["case"] == "PP-D-7002" and facts["Buyer"] == "Emma Liu" and facts["Disputed"].startswith("$180")
    assert req["expires_in"] >= 60
    fraud = [e for e in events if e["type"] == "approval_request" and e["case"] == "PP-D-7003"]
    assert fraud and fraud[0]["amount"] == 1250.0
    resolved = [e for e in events if e["type"] == "approval_resolved"]
    assert resolved and all(e["approved"] is False and e["detail"] == "Too high, offer 20% instead" for e in resolved)
    assert resolved[0]["title"].startswith("Rejected:")


def test_case_note_email_signature_and_jira_context():
    _run(lambda ev: (False, "Offer 20% instead") if "7002" in ev["title"] else True)
    fraud = next(c for c in mock.STATE["cases"] if "7003" in c["title"])["summary"]
    for heading in ("## Problem", "## Evidence", "## Decision", "## Actions taken", "## Next steps"):
        assert heading in fraud
    assert "Alex M" in fraud and "Accepted the claim and refunded $1,250.00 on PayPal (approved by owner)" in fraud
    assert "Opened Jira OPS-" in fraud  # the ticket is linked from the note
    ticket = next(t for t in mock.STATE["jira"] if "KC-1062" in t["summary"])
    assert "Dispute PP-D-7003" in ticket["description"] and "Created by Ledger." in ticket["description"]
    mail = mock.STATE["outbox"][0]["body"]
    assert mail.endswith("Warm regards,\nSwytch Code") and mail.count("regards") == 1


def test_signature_replaces_model_sign_off():
    from app.tools import _signed
    assert _signed("Sorry about the vase.\n\nBest regards,\nKaarigar Co.") == "Sorry about the vase.\n\nWarm regards,\nSwytch Code"
    assert _signed("Sorry about the vase.") == "Sorry about the vase.\n\nWarm regards,\nSwytch Code"


def test_second_run_does_not_repeat_work():
    first = _run(lambda ev: True)
    jira, cases, outbox = len(mock.STATE["jira"]), len(mock.STATE["cases"]), len(mock.STATE["outbox"])
    assert sum(e["type"] == "approval_request" for e in first) == 2

    # Same request again (the scripted model blindly repeats every tool call).
    mock.STATE["disputes"] = __import__("copy").deepcopy(__import__("app.seed", fromlist=["DISPUTES"]).DISPUTES)
    second = _run_keep_state(lambda ev: True)
    assert not [e for e in second if e["type"] == "approval_request"], "must not ask to pay twice"
    assert len(mock.STATE["jira"]) == jira and len(mock.STATE["cases"]) == cases and len(mock.STATE["outbox"]) == outbox
    already = [e for e in second if e["type"] == "tool_result" and "already" in (e.get("detail") or "")]
    assert already, "duplicates are reported back as already done"


def test_work_log_reaches_the_prompt():
    from app import memory
    _run(lambda ev: True)
    text = memory.summary()
    assert "WORK ALREADY DONE" in text and "PP-D-7003" in text and "Jira OPS-" in text
    assert "RECENT CONVERSATION" in text and "Investigate the disputes" in text
