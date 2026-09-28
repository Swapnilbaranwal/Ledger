"""Live backends: every call goes through Swytchcode's runtime (`swytchcode_runtime.exec`).

Setup (once, from server/):
    curl -fsSL https://cli.swytchcode.com/install.sh | sh && swy login && swy init
    swy get paypal notion gmail jira slack --yes
    bash swy_enable.sh                 # enables every id in TOOL_IDS below
    python scripts/fix_endpoints.py    # catalog ships sandbox endpoints as http://localhost
    swy auth connect notion|gmail|jira|slack

Every id can be overridden via env, e.g. SWY_GMAIL_LIST_MESSAGES=gmail.user.messages.get1
"""
from __future__ import annotations

import asyncio
import base64
import os
from datetime import date, datetime, timedelta, timezone
from email.mime.text import MIMEText
from typing import Any

try:
    from swytchcode_runtime import exec as swy_exec, SwytchcodeError
except ImportError:  # keeps mock mode working without the SDK installed
    swy_exec = None

    class SwytchcodeError(Exception):  # type: ignore[no-redef]
        message = "swytchcode-runtime is not installed"


# Canonical ids from `swy list methods`. Entries marked (?) are the best candidate among
# several similarly named variants: confirm with `swy info <id>` (see swy_discover.sh).
TOOL_IDS = {
    "PAYPAL_LIST_TRANSACTIONS": "transaction_search.reporting.transactions.list",
    "PAYPAL_LIST_DISPUTES": "disputes.customer.disputes.list",
    "PAYPAL_GET_DISPUTE": "disputes.customer.disputes.get",
    "PAYPAL_PROVIDE_EVIDENCE": "disputes.customer.provideEvidence.create",
    "PAYPAL_MAKE_OFFER": "disputes.customer.makeOffer.create",
    "PAYPAL_ACCEPT_CLAIM": "disputes.customer.acceptClaim.create",
    "GMAIL_LIST_MESSAGES": "gmail.user.messages.get",       # GET /users/{userId}/messages
    "GMAIL_GET_MESSAGE": "gmail.user.messages.get1",        # GET /users/{userId}/messages/{id}
    "GMAIL_SEND_MESSAGE": "gmail.user.send.create1",        # POST /users/{userId}/messages/send
    "NOTION_SEARCH": "notion.search.create",                # POST /v1/search
    "NOTION_GET_MARKDOWN": "notion.markdown.get",           # GET /v1/pages/{id}/markdown
    "NOTION_SET_MARKDOWN": "notion.markdown.update",        # PATCH /v1/pages/{id}/markdown
    "NOTION_CREATE_PAGE": "notion.page.create",             # POST /v1/pages
    "JIRA_LIST_PROJECTS": "jira.api.search.list5",          # GET /rest/api/3/project/search
    "JIRA_SEARCH": "jira.api.jql.list",                     # GET /rest/api/3/search/jql
    "JIRA_CREATE_ISSUE": "jira.api.issue.create",           # POST /rest/api/3/issue
    "SLACK_POST_MESSAGE": "slack.chat.postmessage.create",
}


def tool_id(key: str) -> str:
    return os.getenv(f"SWY_{key}", TOOL_IDS[key])


SERVER_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DRY_RUN = os.getenv("SWY_DRY_RUN", "0") == "1"   # print the HTTP request instead of sending it


# PayPal methods use unmanaged bearer auth (per `swy info`), so we mint an OAuth
# access token from sandbox client credentials and pass it as Authorization.
_paypal_token: dict = {"value": None, "exp": 0.0}


async def paypal_bearer() -> str | None:
    import time

    static = os.getenv("PAYPAL_ACCESS_TOKEN")
    if static:
        return f"Bearer {static}"
    cid, secret = os.getenv("PAYPAL_CLIENT_ID"), os.getenv("PAYPAL_CLIENT_SECRET")
    if not (cid and secret):
        return None
    if _paypal_token["value"] and time.time() < _paypal_token["exp"] - 60:
        return _paypal_token["value"]
    import httpx

    base = os.getenv("PAYPAL_API_BASE", "https://api-m.sandbox.paypal.com")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"{base}/v1/oauth2/token", auth=(cid, secret),
                              data={"grant_type": "client_credentials"})
        r.raise_for_status()
        data = r.json()
    _paypal_token.update(value=f"Bearer {data['access_token']}", exp=time.time() + data.get("expires_in", 3000))
    return _paypal_token["value"]


def _static_auth(service: str) -> str | None:
    """Only for providers Swytchcode doesn't manage (their `swy info` shows a bearer/basic header).
    If `swy auth connect <service>` works, leave these env vars empty and the CLI injects auth."""
    if service == "JIRA" and os.getenv("JIRA_EMAIL") and os.getenv("JIRA_API_TOKEN"):
        raw = f"{os.environ['JIRA_EMAIL']}:{os.environ['JIRA_API_TOKEN']}".encode()
        return "Basic " + base64.b64encode(raw).decode()
    token = os.getenv(f"{service}_TOKEN")  # NOTION_TOKEN, SLACK_TOKEN, GMAIL_TOKEN
    return f"Bearer {token}" if token else None


async def call(key: str, request: dict) -> Any:
    if swy_exec is None:
        raise RuntimeError("swytchcode-runtime not installed: pip install swytchcode-runtime")
    request = dict(request)
    if key.startswith("PAYPAL_"):
        bearer = await paypal_bearer()
        if bearer:
            request["Authorization"] = bearer
    else:
        auth = _static_auth(key.split("_", 1)[0])
        if auth:
            request["Authorization"] = auth
    if key.startswith("SLACK_"):
        # The runtime validator demands a "token" input although the contract lists only "channel".
        # Top-level it becomes an ignored "Token" header; managed OAuth still injects Authorization.
        request.setdefault("token", "managed-by-swytchcode")
    if key in ("NOTION_GET_MARKDOWN", "NOTION_SET_MARKDOWN"):
        # These two require the header explicitly (their schema default isn't applied).
        request.setdefault("Notion-Version", os.getenv("NOTION_MARKDOWN_VERSION", "2026-03-11"))
    try:
        # cwd must be server/ so the CLI finds .swytchcode/tooling.json
        res = await asyncio.to_thread(swy_exec, tool_id(key), request, cwd=SERVER_DIR, dry_run=DRY_RUN)
    except SwytchcodeError as e:  # surface a readable error to the agent instead of crashing
        return {"ok": False, "error": getattr(e, "message", None) or str(e), "tool_id": tool_id(key)}
    # Live responses arrive as {"data": ..., "request": ..., "status_code": ...}.
    if isinstance(res, dict) and "status_code" in res and "data" in res:
        if int(res["status_code"]) >= 400:
            return {"ok": False, "status": res["status_code"], "error": str(res["data"])[:500], "tool_id": tool_id(key)}
        return res["data"]
    return res


def _money(obj: dict | None) -> tuple[float, str]:
    obj = obj or {}
    return float(obj.get("value", 0) or 0), obj.get("currency_code", "USD")


def _failed(res: Any) -> bool:
    return isinstance(res, dict) and res.get("ok") is False


# ----------------------------------------------------------------------------- PayPal
class SwyPayPal:
    async def sales_summary(self, days: int = 7) -> dict:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        res = await call("PAYPAL_LIST_TRANSACTIONS", {"params": {
            "start_date": start.strftime("%Y-%m-%dT%H:%M:%S-0000"),
            "end_date": end.strftime("%Y-%m-%dT%H:%M:%S-0000"),
            "fields": "transaction_info,payer_info", "page_size": 100}})
        if _failed(res):
            return res
        txs, by_day = [], {}
        for d in (res or {}).get("transaction_details", []):
            ti, pi = d.get("transaction_info", {}), d.get("payer_info", {})
            amt, cur = _money(ti.get("transaction_amount"))
            if amt <= 0:
                continue
            day = (ti.get("transaction_initiation_date") or "")[:10]
            by_day[day] = by_day.get(day, 0) + amt
            txs.append({"id": ti.get("transaction_id"), "date": day, "amount": amt, "currency": cur,
                        "buyer": (pi.get("payer_name") or {}).get("alternate_full_name") or pi.get("email_address")})
        gross = sum(t["amount"] for t in txs)
        return {"days": days, "gross": gross, "orders": len(txs), "today": by_day.get(date.today().isoformat(), 0.0),
                "by_day": by_day, "transactions": txs[:25],
                "note": "month_to_date not available from this API window"}

    async def list_disputes(self) -> list[dict] | dict:
        since = (datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        res = await call("PAYPAL_LIST_DISPUTES", {"params": {
            "page_size": 20, "start_time": since, "next_page_token": None}})
        if _failed(res):
            return res
        out = []
        for d in (res or {}).get("items", []):
            if d.get("status") in ("RESOLVED",):
                continue
            amount, cur = _money(d.get("dispute_amount"))
            out.append({"dispute_id": d.get("dispute_id"), "reason": d.get("reason"), "status": d.get("status"),
                        "amount": amount, "currency": cur, "filed": d.get("create_time"),
                        "respond_by": d.get("seller_response_due_date")})
        return out

    async def get_dispute(self, dispute_id: str) -> dict:
        res = await call("PAYPAL_GET_DISPUTE", {"params": {"id": dispute_id, "dispute_id": dispute_id}})
        if _failed(res):
            return res
        d = res or {}
        amount, cur = _money(d.get("dispute_amount"))
        tx = (d.get("disputed_transactions") or [{}])[0]
        buyer = tx.get("buyer") or {}
        msgs = [m.get("content") for m in d.get("messages", []) if m.get("posted_by") == "BUYER"]
        return {"dispute_id": dispute_id, "reason": d.get("reason"), "status": d.get("status"),
                "amount": amount, "currency": cur, "buyer": buyer.get("name"), "buyer_email": buyer.get("email"),
                "order_id": tx.get("invoice_number") or tx.get("custom"), "transaction_id": tx.get("seller_transaction_id"),
                "respond_by": d.get("seller_response_due_date"), "buyer_message": " | ".join(filter(None, msgs))}

    async def provide_evidence(self, dispute_id: str, summary: str, evidence: list[str]) -> dict:
        body = {"evidences": [{"evidence_type": "OTHER", "notes": f"{summary}\n- " + "\n- ".join(evidence)}]}
        res = await call("PAYPAL_PROVIDE_EVIDENCE", {"params": {"id": dispute_id, "dispute_id": dispute_id}, "body": body})
        return res if _failed(res) else {"ok": True, "dispute_id": dispute_id, "status": "EVIDENCE_SUBMITTED"}

    async def make_offer(self, dispute_id: str, amount: float, note: str) -> dict:
        body = {"note": note, "offer_type": "REFUND",
                "offer_amount": {"currency_code": "USD", "value": f"{amount:.2f}"}}
        res = await call("PAYPAL_MAKE_OFFER", {"params": {"id": dispute_id, "dispute_id": dispute_id}, "body": body})
        return res if _failed(res) else {"ok": True, "dispute_id": dispute_id, "offer_amount": amount}

    async def accept_claim(self, dispute_id: str, note: str) -> dict:
        res = await call("PAYPAL_ACCEPT_CLAIM", {"params": {"id": dispute_id, "dispute_id": dispute_id},
                                                 "body": {"note": note}})
        return res if _failed(res) else {"ok": True, "dispute_id": dispute_id, "status": "ACCEPTED"}


# ----------------------------------------------------------------------------- Gmail
class SwyGmail:
    async def search(self, query: str) -> list[dict] | dict:
        res = await call("GMAIL_LIST_MESSAGES", {"params": {"userId": "me", "q": query, "maxResults": 8}})
        if _failed(res):
            return res
        out = []
        for m in (res or {}).get("messages", [])[:8]:
            full = await call("GMAIL_GET_MESSAGE", {"params": {"userId": "me", "id": m["id"], "format": "full"}})
            if _failed(full):
                continue
            headers = {h["name"].lower(): h["value"] for h in (full.get("payload", {}).get("headers", []))}
            out.append({"id": m["id"], "from": headers.get("from"), "date": headers.get("date"),
                        "subject": headers.get("subject"), "body": _gmail_text(full.get("payload", {})) or full.get("snippet")})
        return out

    async def send_email(self, to: str, subject: str, body: str) -> dict:
        override = os.getenv("DEMO_EMAIL_OVERRIDE")  # route demo mail to your own inbox
        msg = MIMEText(body)
        msg["to"] = override or to
        msg["subject"] = subject if not override else f"[to: {to}] {subject}"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        res = await call("GMAIL_SEND_MESSAGE", {"params": {"userId": "me"}, "body": {"raw": raw}})
        return res if _failed(res) else {"ok": True, "message_id": (res or {}).get("id")}


def _gmail_text(payload: dict) -> str:
    if payload.get("mimeType", "").startswith("text/plain") and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"] + "==").decode("utf-8", "replace")[:1500]
    for part in payload.get("parts", []) or []:
        t = _gmail_text(part)
        if t:
            return t
    return ""


# ----------------------------------------------------------------------------- Notion
def _plain(prop: dict | None) -> str:
    if not prop:
        return ""
    t = prop.get("type")
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in prop.get(t, []))
    if t == "select":
        return (prop.get("select") or {}).get("name", "")
    if t in ("email", "url", "phone_number", "number"):
        return str(prop.get(t) or "")
    if t == "date":
        return (prop.get("date") or {}).get("start", "")
    return str(prop.get(t, ""))


class SwyNotion:
    """Plain pages under a "Ledger" page, created by scripts/live_setup.py:
    NOTION_PLAYBOOK_PAGE_ID (rules), NOTION_ORDERS_PAGE_ID (one "## KC-1042 ..." section per order),
    NOTION_CASES_PAGE_ID (dispute case notes), NOTION_REFUNDS_PAGE_ID (cases where money went back)."""

    REFUND_VERDICTS = ("SETTLED", "ACCEPTED_FRAUD")

    async def _markdown(self, env: str) -> str | dict:
        res = await call("NOTION_GET_MARKDOWN", {"params": {"page_id": os.getenv(env, "")}})
        if _failed(res):
            return res
        return (res or {}).get("markdown") or ""

    async def get_playbook(self) -> str:
        md = await self._markdown("NOTION_PLAYBOOK_PAGE_ID")
        return f"ERROR reading playbook: {md.get('error')}" if isinstance(md, dict) else md

    async def find_orders(self, query: str) -> list[dict] | dict:
        md = await self._markdown("NOTION_ORDERS_PAGE_ID")
        if isinstance(md, dict):
            return md
        terms = [t.lower().removeprefix("from:") for t in query.replace(",", " ").split() if len(t) > 2]
        sections = ["## " + chunk for chunk in md.split("## ")[1:]]
        return [{"order": sec.strip()} for sec in sections if any(t in sec.lower() for t in terms)]

    async def create_page(self, parent_id: str, title: str, markdown: str) -> dict:
        page = await call("NOTION_CREATE_PAGE", {"body": {
            "parent": {"page_id": parent_id},
            "properties": {"title": {"title": [{"text": {"content": title[:200]}}]}}}})
        if _failed(page):
            return page
        if markdown:
            res = await call("NOTION_SET_MARKDOWN", {"params": {"page_id": page["id"]},
                                                     "body": {"type": "insert_content", "insert_content": {"content": markdown}}})
            if _failed(res):
                return res
        return {"ok": True, "id": page["id"], "url": page.get("url")}

    async def log_case(self, title: str, verdict: str, summary: str) -> dict:
        refund = verdict in self.REFUND_VERDICTS
        parent = os.getenv("NOTION_REFUNDS_PAGE_ID" if refund else "NOTION_CASES_PAGE_ID", "")
        body = f"**Verdict:** {verdict}\n\n**Logged by Ledger:** {date.today().isoformat()}\n\n{summary}"
        res = await self.create_page(parent, f"{title} · {verdict}", body)
        if _failed(res):
            return res
        folder = "Refunds" if refund else "Dispute Cases"
        return {"ok": True, "id": res["id"], "folder": folder, "url": res["url"], "label": f"Notion · {folder}: {title}"}

    async def find_case(self, case: str) -> dict | None:
        """An existing case note (under Dispute Cases or Refunds) whose title starts with the case id."""
        res = await call("NOTION_SEARCH", {"body": {"query": case, "page_size": 10,
                                                     "filter": {"property": "object", "value": "page"}}})
        if _failed(res):
            return None
        parents = {os.getenv(k, "").replace("-", "") for k in ("NOTION_CASES_PAGE_ID", "NOTION_REFUNDS_PAGE_ID")}
        for page in (res or {}).get("results", []):
            title = "".join(t.get("plain_text", "") for p in page.get("properties", {}).values()
                            if p.get("type") == "title" for t in p["title"])
            parent = (page.get("parent") or {}).get("page_id", "").replace("-", "")
            if title.startswith(case) and parent in parents and not (page.get("in_trash") or page.get("archived")):
                return {"id": page["id"], "url": page.get("url")}
        return None

    async def append_case(self, existing: dict, markdown: str) -> dict:
        res = await call("NOTION_SET_MARKDOWN", {"params": {"page_id": existing["id"]},
                                                 "body": {"type": "insert_content", "insert_content": {"content": markdown}}})
        return res if _failed(res) else {"ok": True, "url": existing.get("url")}


# ----------------------------------------------------------------------------- Jira / Slack
class SwyJira:
    async def list_open(self) -> list[dict] | dict:
        project = os.getenv("JIRA_PROJECT_KEY", "OPS")
        res = await call("JIRA_SEARCH", {"params": {
            "jql": f"project = {project} AND statusCategory != Done ORDER BY priority DESC",
            "fields": "summary,priority,status,assignee", "maxResults": 20}})
        if _failed(res):
            return res
        out = []
        for i in (res or {}).get("issues", []):
            f = i.get("fields", {})
            out.append({"key": i.get("key"), "summary": f.get("summary"),
                        "priority": (f.get("priority") or {}).get("name"), "status": (f.get("status") or {}).get("name"),
                        "assignee": (f.get("assignee") or {}).get("displayName")})
        return out

    async def find(self, text: str) -> list[dict] | dict:
        """Tickets in the project whose summary mentions `text` (e.g. a dispute id)."""
        project = os.getenv("JIRA_PROJECT_KEY", "OPS")
        res = await call("JIRA_SEARCH", {"params": {"jql": f'project = {project} AND summary ~ "\\"{text}\\""',
                                                    "fields": "summary,status", "maxResults": 20}})
        if _failed(res):
            return res
        site = os.getenv("JIRA_SITE_URL", "").rstrip("/")
        return [{"key": i.get("key"), "summary": (i.get("fields") or {}).get("summary", ""),
                 "status": ((i.get("fields") or {}).get("status") or {}).get("name"),
                 "url": f"{site}/browse/{i.get('key')}" if site else None}
                for i in (res or {}).get("issues", [])]

    async def create_issue(self, summary: str, description: str, priority: str) -> dict:
        fields = {"project": {"key": os.getenv("JIRA_PROJECT_KEY", "OPS")},
                  "issuetype": {"name": os.getenv("JIRA_ISSUE_TYPE", "Task")},
                  "summary": summary,
                  "description": {"type": "doc", "version": 1, "content": [
                      {"type": "paragraph", "content": [{"type": "text", "text": line}]}
                      for line in description.splitlines() if line.strip()]}}
        if os.getenv("JIRA_USE_PRIORITY", "0") == "1":
            fields["priority"] = {"name": priority}
        res = await call("JIRA_CREATE_ISSUE", {"body": {"fields": fields}})
        if _failed(res):
            return res
        key = (res or {}).get("key")
        site = os.getenv("JIRA_SITE_URL", "").rstrip("/")
        return {"ok": True, "key": key, "url": f"{site}/browse/{key}" if site else None,
                "label": f"Jira · {key}: {summary[:60]}"}


class SwySlack:
    async def post_message(self, channel: str, text: str) -> dict:
        channel = os.getenv("SLACK_CHANNEL_OVERRIDE") or channel
        res = await call("SLACK_POST_MESSAGE", {"body": {"channel": channel, "text": text}})
        if _failed(res):
            return res
        if isinstance(res, dict) and res.get("ok") is False:
            return {"ok": False, "error": res.get("error")}
        channel_id = (res or {}).get("channel") or channel
        return {"ok": True, "channel": channel, "url": f"https://slack.com/app_redirect?channel={channel_id}",
                "label": f"Slack · posted to {channel}"}
