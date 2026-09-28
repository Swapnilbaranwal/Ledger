"""Check each Swytchcode call Ledger makes.   python scripts/swy_smoke.py [--live]
Default is --dry-run (shows the HTTP request, sends nothing)."""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()
if "--live" not in sys.argv:
    os.environ["SWY_DRY_RUN"] = "1"
from app.backends import swytch  # noqa: E402

async def main():
    pp = swytch.SwyPayPal()
    for name, coro in [("list invoices", swytch.call("PAYPAL_LIST_INVOICES", {"params": {"page_size": 5}})),
                       ("list disputes", swytch.call("PAYPAL_LIST_DISPUTES", {"params": {"dispute_state": "OPEN_INQUIRIES", "page_size": 20, "start_time": "2026-04-01T00:00:00.000Z", "next_page_token": None}}))]:
        print(f"\n===== {name}")
        print(json.dumps(await coro, indent=1, default=str)[:1500])
    if "--live" in sys.argv:
        print("\n===== normalized invoices"); print(json.dumps(await pp.list_invoices(), indent=1)[:1500])

asyncio.run(main())
