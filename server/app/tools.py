"""Tools the agent (Ledger — AI COO + Chargeback Detective) can choose from. Each one:
  1. emits a `tool_call` event (the iOS timeline shows which API the agent picked),
  2. executes via the selected backend (Swytchcode or mock),
  3. emits a `tool_result` event with a short preview.
Money-moving tools are gated by a hard, code-level human approval.
"""
from __future__ import annotations

import asyncio
from datetime import date
import contextlib
import functools
import json
import os
import re
from typing import Any, Awaitable, Callable, Literal

from langchain_core.tools import tool

from . import backends, memory
from .events import get_run_context, short


@contextlib.asynccontextmanager
async def _busy():
    """Count running tool calls so the Notion case note can wait for its siblings (see notion_log_case)."""
    ctx = get_run_context()
    ctx.inflight += 1
    try:
        yield
    finally:
        ctx.inflight -= 1


def traced(service: str, label: str):
    """Wrap a tool coroutine with timeline events + error capture."""

    def deco(fn: Callable[..., Awaitable[Any]]):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            async with _busy():
                return await _traced_call(fn, service, label, args, kwargs)

        return wrapper

    return deco


async def _traced_call(fn, service: str, label: str, args, kwargs):
    ctx = get_run_context()
    ctx.stats["tool_calls"] += 1
    ctx.stats["services"].add(service)
    via = "Swytchcode" if backends.mode(service) == "swytch" else "mock"
    await ctx.emit("tool_call", title=label, detail=short(kwargs, 400) if kwargs else None,
                   service=service, tool=fn.__name__, via=via)
    try:
        result = await fn(*args, **kwargs)
    except Exception as e:  # never crash the graph: let the agent reason about the failure
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    failed = isinstance(result, dict) and result.get("ok") is False
    await ctx.emit("tool_result", title=f"{label} → {'failed' if failed else 'done'}",
                   detail=short(result), service=service, tool=fn.__name__, ok=not failed)
    if not failed and isinstance(result, dict) and result.get("url"):
        # Business tab: a tappable link to what was created (Jira ticket, Notion page, Slack post).
        await ctx.emit("link", title=result.get("label") or label, detail=result["url"],
                       service=service, url=result["url"])
    return json.dumps(result, default=str) if not isinstance(result, str) else result


# ------------------------------------------------------------------ Case file
# Everything Ledger does for a dispute is recorded per case, so the Notion note, the Jira tickets
# and the approval card all tell the same story from one place.
_CASE_RE = re.compile(r"PP-D-\d+")


def _case_for(*texts: str | None) -> str | None:
    ctx = get_run_context()
    blob = " ".join(t for t in texts if t)
    if m := _CASE_RE.search(blob):
        return m.group(0)
    low = blob.lower()
    known = {**memory.load()["cases"], **ctx.disputes}  # this request's disputes + ones handled before
    for case, d in known.items():
        keys = [str(d.get("buyer_email", "")).lower()] + [o.strip().lower() for o in str(d.get("order_id", "")).split(",")]
        if any(k and k in low for k in keys):
            return case
    return None


def _log_action(case: str | None, text: str) -> None:
    if case:
        get_run_context().actions.setdefault(case, []).append(text)


def _remember_dispute(d: Any) -> None:
    if isinstance(d, dict) and d.get("dispute_id"):
        get_run_context().disputes[d["dispute_id"]] = d
        memory.update(d["dispute_id"], buyer=d.get("buyer"), buyer_email=d.get("buyer_email"),
                      order_id=d.get("order_id"))


def _already(message: str, **extra: Any) -> dict:
    """Returned instead of repeating work; the agent should report it, not retry."""
    return {"ok": True, "already_done": True, "message": message, **extra}


def _claim(d: dict) -> str:
    return str(d.get("reason", "")).replace("MERCHANDISE_OR_SERVICE_", "").replace("_", " ").capitalize()


def _money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


# ------------------------------------------------------------------ PayPal
@tool
@traced("paypal", "PayPal · sales summary")
async def paypal_sales_summary(days: int = 7) -> Any:
    """Revenue for the last N days: gross, order count, today's sales, per-day totals, month_to_date."""
    return await backends.get("paypal").sales_summary(days)


@tool
@traced("paypal", "PayPal · list open disputes")
async def paypal_list_disputes() -> Any:
    """List open PayPal disputes (chargebacks, not-received, not-as-described, unauthorised). Disputes
    Ledger already handled carry a `ledger` field: don't redo them."""
    res = await backends.get("paypal").list_disputes()
    if isinstance(res, list):
        for d in res:
            if status := memory.status_of(d.get("dispute_id", "")):
                d["ledger"] = status
    return res


@tool
@traced("paypal", "PayPal · get dispute details")
async def paypal_get_dispute(dispute_id: str) -> Any:
    """Full details of one dispute: reason, amount, buyer email, order id, buyer's message, respond-by date."""
    d = await backends.get("paypal").get_dispute(dispute_id)
    _remember_dispute(d)
    return d


@tool
@traced("paypal", "PayPal · submit evidence")
async def paypal_provide_evidence(dispute_id: str, summary: str, evidence: list[str]) -> Any:
    """Contest a dispute by submitting evidence to PayPal (tracking/delivery proof, buyer's own messages).
    `evidence` is a list of short, factual evidence statements with dates."""
    if done := memory.contested(dispute_id):
        return _already(f"{dispute_id} was already contested on {done['at']}. Evidence not submitted again.")
    res = await backends.get("paypal").provide_evidence(dispute_id, summary, evidence)
    if not (isinstance(res, dict) and res.get("ok") is False):
        text = f"Contested on PayPal with {len(evidence)} pieces of evidence: {summary}"
        _log_action(dispute_id, text)
        memory.record(dispute_id, "paypal", action="evidence", text=text)
    return res


async def _money_gate(action: str, reason: str, amount: float, dispute_id: str) -> dict:
    """Ask the owner, with the facts they need to decide: who, what they claim, how much, the evidence."""
    d = await backends.get("paypal").get_dispute(dispute_id)
    _remember_dispute(d)
    facts = []
    if isinstance(d, dict) and d.get("ok") is not False:
        for label, key in (("Buyer", "buyer"), ("Order", "order_id"), ("Claim", "reason"),
                           ("Disputed", "amount"), ("Respond by", "respond_by"), ("Buyer says", "buyer_message")):
            if d.get(key) not in (None, ""):
                value = d[key]
                if key == "reason":
                    value = str(value).replace("MERCHANDISE_OR_SERVICE_", "").replace("_", " ").capitalize()
                if key == "amount":
                    value = f"${float(value):,.2f} {d.get('currency', 'USD')}"
                facts.append({"label": label, "value": str(value)})
    return await get_run_context().request_approval(action=action, reason=reason, amount=amount,
                                                    service="paypal", case=dispute_id, facts=facts)


def _log_decision(dispute_id: str, what: str, decision: dict, result: str | None = None, action: str = "") -> None:
    ok = False
    if decision["approved"]:
        ok = result is None or json.loads(result).get("ok") is not False
        text = f"{what} (approved by owner)" + ("" if ok else ", but PayPal returned an error")
    elif decision["expired"]:
        text = f"{what}: owner did not answer in time, nothing paid"
    else:
        reason = f': "{decision["note"]}"' if decision["note"] else ""
        text = f"{what}: rejected by owner{reason}. Nothing paid"
    _log_action(dispute_id, text)
    memory.record(dispute_id, "paypal", action=action, approved=bool(decision["approved"] and ok), text=text)


def _money_already_done(dispute_id: str) -> str | None:
    if done := memory.done_money(dispute_id):
        return json.dumps(_already(f"Money already moved on {dispute_id} ({done['text']}, {done['at']}). "
                                   "Not asking the owner or paying again."))
    return None


def _rejected(decision: dict) -> str:
    if decision["expired"]:
        message = "No answer from the founder in time. Do not retry; log the case as PENDING_FOUNDER."
    else:
        message = "Founder rejected. Do not retry; log the case as PENDING_FOUNDER."
        if decision["note"]:
            message += f' Founder\'s reason: "{decision["note"]}". Follow it in the case note and summary.'
    return json.dumps({"ok": False, "status": "EXPIRED" if decision["expired"] else "REJECTED_BY_FOUNDER",
                       "message": message})


@tool
async def paypal_make_offer(dispute_id: str, amount: float, note: str) -> str:
    """Offer the buyer a partial refund to settle a dispute. Moves money, so ALWAYS needs the
    founder's approval (enforced by the system)."""
    async with _busy():
        if done := _money_already_done(dispute_id):
            return done
        decision = await _money_gate(f"Offer ${amount:,.2f} partial refund on {dispute_id}", note, amount, dispute_id)
        if not decision["approved"]:
            _log_decision(dispute_id, f"Partial refund offer of ${amount:,.2f}", decision, action="offer")
            return _rejected(decision)

        @traced("paypal", "PayPal · make settlement offer")
        async def _do(dispute_id: str, amount: float, note: str):
            return await backends.get("paypal").make_offer(dispute_id, amount, note)

        result = await _do(dispute_id=dispute_id, amount=amount, note=note)
        _log_decision(dispute_id, f"Offered a ${amount:,.2f} partial refund on PayPal", decision, result, action="offer")
        return result


@tool
async def paypal_accept_claim(dispute_id: str, amount: float, note: str) -> str:
    """Accept the buyer's claim (full refund). Use for confirmed fraud or unusable items. Moves money,
    so ALWAYS needs the founder's approval (enforced by the system)."""
    async with _busy():
        if done := _money_already_done(dispute_id):
            return done
        decision = await _money_gate(f"Accept claim & refund ${amount:,.2f} on {dispute_id}", note, amount, dispute_id)
        if not decision["approved"]:
            _log_decision(dispute_id, f"Full refund of ${amount:,.2f}", decision, action="refund")
            return _rejected(decision)

        @traced("paypal", "PayPal · accept claim")
        async def _do(dispute_id: str, note: str):
            return await backends.get("paypal").accept_claim(dispute_id, note)

        result = await _do(dispute_id=dispute_id, note=note)
        _log_decision(dispute_id, f"Accepted the claim and refunded ${amount:,.2f} on PayPal", decision, result, action="refund")
        return result


# ------------------------------------------------------------------ Gmail
@tool
@traced("gmail", "Gmail · search inbox")
async def gmail_search(query: str) -> Any:
    """Search the business inbox. Use buyer email addresses, order ids or keywords, e.g.
    'john.carter@example.com' or 'KC-1042'. Returns sender, date, subject and body."""
    return await backends.get("gmail").search(query)


@tool
@traced("gmail", "Gmail · send email")
async def gmail_send_email(to: str, subject: str, body: str) -> Any:
    """Send an email from the business mailbox (e.g. an apology + offer to a buyer). Warm, concise, plain
    text. Do not sign it: the company signature is added automatically."""
    if done := memory.sent_email(to, subject):
        return _already(f'An email "{done["subject"]}" was already sent to {to} on {done["at"]}. Not sending again.')
    res = await backends.get("gmail").send_email(to, subject, _signed(body))
    if not (isinstance(res, dict) and res.get("ok") is False):
        case = _case_for(to, subject, body)
        _log_action(case, f'Emailed {to}: "{subject}"')
        memory.record_email(case, to, subject)
    return res


EMAIL_SIGNATURE = os.getenv("EMAIL_SIGNATURE", "Warm regards,\nSwytch Code")
_SIGN_OFF = re.compile(r"^(warm|kind|best|many)?\s*(regards|wishes)|^(sincerely|cheers|best|thanks|thank you)\b", re.I)


def _signed(body: str) -> str:
    """Replace whatever sign-off the model wrote with the company signature."""
    lines = body.rstrip().splitlines()
    for i in range(len(lines) - 1, max(len(lines) - 5, -1), -1):
        if _SIGN_OFF.match(lines[i].strip()):
            lines = lines[:i]
            break
    return "\n".join(lines).rstrip() + "\n\n" + EMAIL_SIGNATURE


# ------------------------------------------------------------------ Notion
@tool
@traced("notion", "Notion · read ops playbook")
async def notion_get_playbook() -> Any:
    """Read the founder's ops playbook: revenue target, dispute policy, brief format. Always follow it."""
    return await backends.get("notion").get_playbook()


@tool
@traced("notion", "Notion · look up orders")
async def notion_find_orders(query: str) -> Any:
    """Find orders in the Notion order log by order id, customer name or email. Returns items, shipping,
    tracking status, ship-to address and warehouse/QC notes."""
    return await backends.get("notion").find_orders(query)


@tool
@traced("notion", "Notion · log case file")
async def notion_log_case(title: str, verdict: Literal["CONTESTED", "SETTLED", "ACCEPTED_FRAUD", "PENDING_FOUNDER"],
                          summary: str) -> Any:
    """Create the case note in Notion AFTER acting on the dispute (and after its Jira tickets): the note
    collects the problem, evidence, decision, every action taken and next steps automatically. `summary`
    is your one-paragraph reasoning for the decision. SETTLED and ACCEPTED_FRAUD notes are filed under
    Refunds; CONTESTED and PENDING_FOUNDER under Dispute Cases."""
    ctx = get_run_context()
    await asyncio.sleep(0.05)  # let tool calls from the same step start
    deadline = asyncio.get_running_loop().time() + ctx.approval_timeout + 60
    while ctx.inflight > 1 and asyncio.get_running_loop().time() < deadline:  # 1 = this call
        await asyncio.sleep(0.2)
    case = _case_for(title, summary)
    notion = backends.get("notion")
    existing = (memory.case(case).get("notion") or [None])[0] if case else None
    if case and not existing:
        existing = await notion.find_case(case)
    if existing and (existing.get("id") or existing.get("page")):
        if not ctx.actions.get(case):
            return _already(f"{case} already has a Notion note and nothing new happened, so it was not changed.",
                            url=existing.get("url"), label=f"Notion · {case} note (existing)")
        res = await notion.append_case(existing, _case_note(case, verdict, summary, update=True))
        if isinstance(res, dict) and res.get("ok") is not False:
            memory.update(case, verdict=verdict)
            res = {**res, "updated_existing": True, "label": f"Notion · {case} note updated"}
        return res
    res = await notion.log_case(title, verdict, _case_note(case, verdict, summary))
    if case and isinstance(res, dict) and res.get("ok") is not False:
        memory.set_note(case, id=res.get("id"), url=res.get("url"), page=res.get("page"), folder=res.get("folder"))
        memory.update(case, verdict=verdict)
    return res


NEXT_STEPS = {
    "CONTESTED": "Wait for PayPal's decision on the evidence. The Jira ticket tracks it.",
    "SETTLED": "Wait for the buyer to accept the offer, then close the Jira ticket. Fix the root cause ticket.",
    "ACCEPTED_FRAUD": "Make sure the stop-shipment ticket is done and block this buyer.",
    "PENDING_FOUNDER": "Owner decision needed. See the owner's reason under Actions taken.",
}


def _case_note(case: str | None, verdict: str, summary: str, update: bool = False) -> str:
    ctx = get_run_context()
    if update:
        actions = ctx.actions.get(case or "") or ["No new actions."]
        return "\n".join([f"## Update {date.today().isoformat()}", f"**{verdict}**: {summary}", "",
                          "### Actions taken", *[f"- {a}" for a in actions], "",
                          "### Next steps", f"- {NEXT_STEPS.get(verdict, 'Review the case.')}"])
    d = ctx.disputes.get(case or "", {})
    problem = [f"- **Dispute:** {case or 'unknown'}" + (f" ({_claim(d)})" if d.get("reason") else "")]
    if d:
        problem += [f"- **Buyer:** {d.get('buyer', '')} ({d.get('buyer_email', '')})",
                    f"- **Order:** {d.get('order_id', '')}",
                    f"- **Disputed amount:** {_money(d.get('amount'))} {d.get('currency', '')}",
                    f"- **Respond by:** {d.get('respond_by', '')}"]
        if d.get("buyer_message"):
            problem.append(f"- **Buyer says:** \"{d['buyer_message']}\"")
    evidence = ctx.findings.get(case or "") or ["No evidence was pinned."]
    actions = ctx.actions.get(case or "") or ["No actions recorded."]
    return "\n".join([
        "## Problem", *problem, "",
        "## Evidence", *[f"- {e}" for e in evidence], "",
        "## Decision", f"**{verdict}**: {summary}", "",
        "## Actions taken", *[f"- {a}" for a in actions], "",
        "## Next steps", f"- {NEXT_STEPS.get(verdict, 'Review the case.')}",
    ])


# ------------------------------------------------------------------ Jira
@tool
@traced("jira", "Jira · list open issues")
async def jira_list_open_issues() -> Any:
    """List open Ops/engineering issues (for the daily brief: top blockers)."""
    return await backends.get("jira").list_open()


@tool
@traced("jira", "Jira · create ticket")
async def jira_create_issue(summary: str, description: str,
                            priority: Literal["Highest", "High", "Medium", "Low"] = "High") -> Any:
    """Create a Jira ticket for work the team must resolve: one per dispute saying what is still open,
    plus one per fix (stop a pending shipment, fix warehouse QC, restock, block a buyer). Start the summary
    with the dispute id. Dispute facts and evidence are appended to the description automatically."""
    case = _case_for(summary, description)
    for _ in range(25):  # a sibling call in this step may still be loading the dispute (e.g. an approval)
        if case or get_run_context().inflight <= 1:
            break
        await asyncio.sleep(0.2)
        case = _case_for(summary, description)
    d = get_run_context().disputes.get(case or "", {})
    if d:
        evidence = get_run_context().findings.get(case, [])
        description += (f"\n\nDispute {case}: {_claim(d)}, {d.get('buyer', '')} ({d.get('buyer_email', '')}), "
                        f"order {d.get('order_id', '')}, {_money(d.get('amount'))}. Respond by {d.get('respond_by', '')}."
                        + ("\nEvidence:\n" + "\n".join(f"- {e}" for e in evidence) if evidence else "")
                        + "\nCreated by Ledger.")
    if case:
        known = memory.find_ticket(case, summary)
        if not known:  # tickets created before the work log existed, or by hand
            found = await backends.get("jira").find(case)
            if isinstance(found, list):
                known = memory.match_ticket(summary, found)
                if known:
                    memory.record(case, "jira", key=known.get("key"), summary=known.get("summary"), url=known.get("url"))
        if known:
            return _already(f"Jira {known.get('key')} already tracks this for {case}: \"{known.get('summary')}\". "
                            "No duplicate created.", key=known.get("key"), url=known.get("url"),
                            label=f"Jira · {known.get('key')} already exists")
    res = await backends.get("jira").create_issue(summary, description, priority)
    if isinstance(res, dict) and res.get("ok") is not False:
        key = res.get("key", "ticket")
        link = f"[{key}]({res['url']})" if res.get("url") else key
        _log_action(case, f"Opened Jira {link}: {summary}")
        memory.record(case, "jira", key=key, summary=summary, url=res.get("url"))
    return res


# ------------------------------------------------------------------ Slack
@tool
@traced("slack", "Slack · post message")
async def slack_post_message(channel: str, text: str) -> Any:
    """Post to the team Slack channel, e.g. '#general'. Include Jira/Notion links for each case."""
    return await backends.get("slack").post_message(channel, _slack_mrkdwn(text))


def _slack_mrkdwn(text: str) -> str:
    """Models write Markdown; Slack wants <url|label> links and *bold*."""
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"<\2|\1>", text)
    return re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)


# ------------------------------------------------------------------ Detective notebook (UI only)
@tool
async def record_finding(case: str, finding: str, points_to: Literal["merchant", "buyer", "fraud", "neutral"]) -> str:
    """Pin a key piece of evidence to the case board shown to the founder (e.g. a delivery signature or
    the buyer's own email). Call it for each decisive clue before deciding a case."""
    ctx = get_run_context()
    ctx.findings.setdefault(case, []).append(finding)
    await ctx.emit("finding", title=finding, detail=case, points_to=points_to)
    return json.dumps({"ok": True})


ALL_TOOLS = [
    paypal_sales_summary, paypal_list_disputes, paypal_get_dispute, paypal_provide_evidence,
    paypal_make_offer, paypal_accept_claim,
    gmail_search, gmail_send_email,
    notion_get_playbook, notion_find_orders, notion_log_case,
    jira_list_open_issues, jira_create_issue,
    slack_post_message, record_finding,
]

SERVICE_OF = {t.name: ("notebook" if t.name == "record_finding" else t.name.split("_", 1)[0]) for t in ALL_TOOLS}
