"""One-time setup for live Notion / Gmail / Jira (after `swy auth connect ...`).

    python scripts/live_setup.py notion [PARENT_PAGE_ID]   # Ledger page + Playbook, Orders, Dispute Cases, Refunds
    python scripts/live_setup.py playbook                  # push app/seed.py's PLAYBOOK rules to the Notion page
    python scripts/live_setup.py gmail                     # demo buyer emails into your inbox (evidence to find)
    python scripts/live_setup.py jira https://YOURSITE.atlassian.net [PROJECT_KEY]

Each step writes the ids it creates into server/.env. Safe to re-run: Notion skips if already set up.
"""
import asyncio
import base64
import json
import os
import re
import subprocess
import sys
import urllib.request
from email.mime.text import MIMEText

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

ENV = os.path.join(ROOT, ".env")
load_dotenv(ENV, override=True)
from app import seed  # noqa: E402
from app.backends.swytch import SwyNotion, _failed, call  # noqa: E402


def set_env(**values: str) -> None:
    """Replace KEY=... lines in .env (or append them)."""
    text = open(ENV).read()
    for key, value in values.items():
        line = f"{key}={value}"
        text, n = re.subn(rf"(?m)^#?\s*{key}=.*$", line, text, count=1)
        if not n:
            text += ("" if text.endswith("\n") else "\n") + line + "\n"
        os.environ[key] = value
        print(f"  .env  {line}")
    open(ENV, "w").write(text)


def die(what: str, res) -> None:
    sys.exit(f"{what} failed: {json.dumps(res, default=str)[:600]}")


# ---------------------------------------------------------------- Notion
def orders_markdown() -> str:
    parts = []
    for o in seed.ORDERS:
        rows = [("Customer", o["customer"]), ("Email", o["email"]), ("Country", o["country"]),
                ("Items", o["items"]), ("Amount", f"${o['amount']:.0f}"), ("Shipped", o.get("shipped") or "not yet"),
                ("Carrier", o["carrier"]), ("Tracking", o.get("tracking") or "none"),
                ("Tracking status", o["tracking_status"]), ("Ship to", o.get("ship_to") or "customer address"),
                ("Notes", o.get("notes") or "-")]
        parts.append(f"## {o['order_id']} · {o['customer']}\n" + "\n".join(f"- **{k}:** {v}" for k, v in rows))
    return "\n\n".join(parts)


async def find_parent() -> str:
    res = await call("NOTION_SEARCH", {"body": {"page_size": 50, "filter": {"property": "object", "value": "page"}}})
    if _failed(res):
        die("Notion search", res)
    top = [p for p in res.get("results", []) if (p.get("parent") or {}).get("type") == "workspace"]
    if not top:
        sys.exit("No top-level Notion page is shared with Swytchcode. Re-run `swy auth connect notion` "
                 "and share a page, or pass its id: python scripts/live_setup.py notion <page_id>")
    return top[0]["id"]


async def notion(parent: str | None) -> None:
    if os.getenv("NOTION_REFUNDS_PAGE_ID"):
        print("Notion already set up (NOTION_REFUNDS_PAGE_ID is in .env). Delete those lines to redo it.")
        return
    n = SwyNotion()
    if os.getenv("NOTION_LEDGER_PAGE_ID"):  # reuse the Ledger page from an earlier, partial run
        ledger = {"id": os.environ["NOTION_LEDGER_PAGE_ID"], "url": "(existing Ledger page)"}
    else:
        parent = parent or await find_parent()
        ledger = await n.create_page(parent, "Ledger", "")
        if _failed(ledger):
            die("Create Ledger page", ledger)
        set_env(NOTION_LEDGER_PAGE_ID=ledger["id"])
    ids = {}
    for key, title, body in [
        ("NOTION_PLAYBOOK_PAGE_ID", "Playbook", seed.PLAYBOOK.split("\n", 1)[1].strip()),
        ("NOTION_ORDERS_PAGE_ID", "Orders", orders_markdown()),
        ("NOTION_CASES_PAGE_ID", "Dispute Cases", "Case notes for contested and pending disputes, one page each."),
        ("NOTION_REFUNDS_PAGE_ID", "Refunds", "Case notes where money went back to the buyer (settlements, accepted claims)."),
    ]:
        page = await n.create_page(ledger["id"], title, body)
        if _failed(page):
            die(f"Create {title}", page)
        ids[key] = page["id"]
        print(f"  created {title}: {page['url']}")
    set_env(**ids)
    print(f"Notion ready: {ledger['url']}")


# ---------------------------------------------------------------- Gmail
async def gmail() -> None:
    me = os.getenv("DEMO_EMAIL_OVERRIDE")
    if not me or me == "you@gmail.com":
        sys.exit("Set DEMO_EMAIL_OVERRIDE=<your gmail> in .env first.")
    for m in seed.INBOX[:4]:
        body = f"Original sender: {m['from']}\nDate: {m['date']}\n\n{m['body']}"
        msg = MIMEText(body)
        msg["to"], msg["subject"] = me, f"[Ledger demo] {m['subject']} (from {m['from']})"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        res = await call("GMAIL_SEND_MESSAGE", {"params": {"userId": "me"}, "body": {"raw": raw}})
        if _failed(res):
            die("Gmail send", res)
        print(f"  sent: {msg['subject']}")
    print("Gmail ready: Ledger's inbox search will find these by buyer email or order id.")


# ---------------------------------------------------------------- Jira
async def jira(site: str, project: str | None) -> None:
    site = site.rstrip("/")
    with urllib.request.urlopen(f"{site}/_edge/tenant_info", timeout=15) as r:
        cloud_id = json.load(r)["cloudId"]
    api = f"https://api.atlassian.com/ex/jira/{cloud_id}"  # OAuth apps must call Jira through this host
    subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "fix_endpoints.py"), api],
                   check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
    res = await call("JIRA_LIST_PROJECTS", {"params": {"maxResults": 50}})
    if _failed(res):
        die("Jira list projects", res)
    projects = [(p["key"], p["name"]) for p in res.get("values", [])]
    print("  projects:", ", ".join(f"{k} ({n})" for k, n in projects) or "none")
    if not projects:
        sys.exit("Create a Jira project first (e.g. key OPS), then re-run.")
    keys = [k for k, _ in projects]
    key = project or ("OPS" if "OPS" in keys else keys[0])
    if key not in keys:
        sys.exit(f"Project {key} not found. Pick one of: {', '.join(keys)}")
    set_env(JIRA_SITE_URL=site, JIRA_PROJECT_KEY=key)
    print(f"Jira ready: tickets go to {site}/browse/{key}")


async def playbook() -> None:
    """Overwrite the Notion Playbook page with app/seed.py's PLAYBOOK (after editing the rules there)."""
    res = await call("NOTION_SET_MARKDOWN", {"params": {"page_id": os.environ["NOTION_PLAYBOOK_PAGE_ID"]}, "body": {
        "type": "replace_content",
        "replace_content": {"new_str": seed.PLAYBOOK.split("\n", 1)[1].strip(), "allow_deleting_content": True}}})
    if _failed(res):
        die("Update playbook", res)
    print("Notion Playbook updated.")


if __name__ == "__main__":
    step, args = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    if step == "notion":
        asyncio.run(notion(args[0] if args else None))
    elif step == "playbook":
        asyncio.run(playbook())
    elif step == "gmail":
        asyncio.run(gmail())
    elif step == "jira" and args:
        asyncio.run(jira(args[0], args[1] if len(args) > 1 else None))
    else:
        sys.exit(__doc__)
