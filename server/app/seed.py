"""Demo world for mock mode: Kaarigar Co., a Jaipur blue-pottery & brass-lamp
exporter that sells worldwide through PayPal. Dates are relative to today."""
from __future__ import annotations

import copy
from datetime import date, datetime, time, timedelta

PLAYBOOK = """# Kaarigar Co. — Ops Playbook (owned by the founder)

## Targets
- Monthly revenue target: $18,000.

## Disputes (PayPal)
1. Respond to every dispute within 3 days of it being filed.
2. CONTEST with evidence when we have proof of delivery AND the buyer confirmed receipt.
3. OUR FAULT (wrong/damaged item): offer a partial refund of up to 40% and let the buyer keep
   the item. If the item is unusable, refund in full.
4. FRAUD pattern (new PayPal account + several orders in a short window + ship-to a freight
   forwarder): accept the claim, open a HIGH priority Jira ticket for Ops to stop any pending
   shipment for that buyer, and alert Slack #general.
5. Any action that moves money (offers, refunds, accepting claims) needs founder approval.
6. When the mistake is ours, email the buyer an apology (signed "Warm regards, Swytch Code").
7. Jira is for what the team must resolve: one ticket per dispute saying what is still open, plus one
   ticket per fix (stop a shipment, fix warehouse QC, restock, block a buyer).
8. Log every case in Notion with the problem, evidence, decision, actions taken and next steps
   (refunds and settlements are filed under Refunds automatically). Post one summary to Slack #general.

## Daily brief format
Revenue vs target, disputes at risk ($), top open blocker, and ONE recommended action.
"""


def _d(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _ts(days_ago: int, hh: int, mm: int = 0) -> str:
    return datetime.combine(date.today() - timedelta(days=days_ago), time(hh, mm)).isoformat(timespec="minutes")


def _transactions() -> list[dict]:
    rows = [
        (0, "Olivia Brown", "US", 260), (0, "Lukas Meyer", "DE", 145), (0, "Sofia Rossi", "IT", 310),
        (1, "Noah Wilson", "US", 520), (1, "Aiko Tanaka", "JP", 95), (1, "Emma Liu", "GB", 180),
        (2, "Chloé Martin", "FR", 240), (2, "Alex M", "US", 410), (2, "Alex M", "US", 390),
        (2, "Alex M", "US", 450), (3, "Liam Smith", "AU", 175), (4, "John Carter", "US", 420),
        (5, "Mia Johnson", "CA", 330), (6, "Ravi Kapoor", "SG", 610),
    ]
    out = []
    for i, (ago, name, cc, amt) in enumerate(rows):
        out.append({"id": f"TX-{9100 + i}", "date": _d(ago), "buyer": name, "country": cc,
                    "amount": float(amt), "currency": "USD", "status": "COMPLETED"})
    return out


DISPUTES = [
    {"dispute_id": "PP-D-7001", "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "status": "OPEN",
     "amount": 420.0, "currency": "USD", "buyer": "John Carter", "buyer_email": "john.carter@example.com",
     "order_id": "KC-1042", "transaction_id": "TX-9111", "filed": _d(2), "respond_by": _d(-1),
     "buyer_message": "I never received my brass lamp. I want my money back."},
    {"dispute_id": "PP-D-7002", "reason": "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "status": "OPEN",
     "amount": 180.0, "currency": "USD", "buyer": "Emma Liu", "buyer_email": "emma.liu@example.co.uk",
     "order_id": "KC-1051", "transaction_id": "TX-9105", "filed": _d(1), "respond_by": _d(-2),
     "buyer_message": "I ordered a cobalt blue vase and received a teal one."},
    {"dispute_id": "PP-D-7003", "reason": "UNAUTHORISED", "status": "OPEN",
     "amount": 1250.0, "currency": "USD", "buyer": "Alex M", "buyer_email": "alex.m.buys@example.net",
     "order_id": "KC-1060, KC-1061, KC-1062", "transaction_id": "TX-9107,TX-9108,TX-9109", "filed": _d(0),
     "respond_by": _d(-3),
     "buyer_message": "Cardholder reports these payments were not made by them."},
]

ORDERS = [
    {"order_id": "KC-1042", "customer": "John Carter", "email": "john.carter@example.com", "country": "US",
     "items": "Hand-etched brass lamp (large)", "amount": 420.0, "shipped": _d(12), "carrier": "DHL Express",
     "tracking": "DHL 4455 2981 07", "tracking_status": f"DELIVERED {_d(8)} 14:12 — signed by 'J CARTER'",
     "notes": "Account age 3 years, 4 previous orders, no disputes."},
    {"order_id": "KC-1051", "customer": "Emma Liu", "email": "emma.liu@example.co.uk", "country": "GB",
     "items": "Blue pottery vase — cobalt (listing photo)", "amount": 180.0, "shipped": _d(9),
     "carrier": "India Post EMS", "tracking": "EE 5512 998 IN", "tracking_status": f"DELIVERED {_d(3)}",
     "notes": "QC: cobalt out of stock — warehouse packed TEAL variant. Customer NOT informed."},
    {"order_id": "KC-1060", "customer": "Alex M", "email": "alex.m.buys@example.net", "country": "US",
     "items": "Brass lamp set (3)", "amount": 410.0, "shipped": _d(1), "carrier": "FedEx",
     "tracking": "FX 7781 0021", "tracking_status": "IN TRANSIT",
     "ship_to": "Global Fwd LLC, 22 Harbor Rd, Wilmington DE (freight forwarder)",
     "notes": "PayPal account created 1 day before purchase. 3 orders within 40 minutes."},
    {"order_id": "KC-1061", "customer": "Alex M", "email": "alex.m.buys@example.net", "country": "US",
     "items": "Blue pottery dinner set", "amount": 390.0, "shipped": _d(1), "carrier": "FedEx",
     "tracking": "FX 7781 0022", "tracking_status": "IN TRANSIT",
     "ship_to": "Global Fwd LLC, 22 Harbor Rd, Wilmington DE (freight forwarder)", "notes": ""},
    {"order_id": "KC-1062", "customer": "Alex M", "email": "alex.m.buys@example.net", "country": "US",
     "items": "Hand-painted wall plates (6)", "amount": 450.0, "shipped": None, "carrier": "FedEx",
     "tracking": None, "tracking_status": "PACKED — NOT YET SHIPPED (pickup scheduled tomorrow)",
     "ship_to": "Global Fwd LLC, 22 Harbor Rd, Wilmington DE (freight forwarder)", "notes": ""},
]

INBOX = [
    {"id": "m1", "from": "john.carter@example.com", "date": _ts(7, 21, 4), "subject": "Re: Your Kaarigar order KC-1042",
     "body": "Hi! The lamp arrived yesterday and it looks stunning in our living room. The etching is "
             "incredible. Thank you so much — will order again for my sister's wedding. — John"},
    {"id": "m2", "from": "emma.liu@example.co.uk", "date": _ts(2, 10, 30), "subject": "Wrong colour vase (order KC-1051)",
     "body": "Hello, I ordered the cobalt blue vase shown in the photos but received a teal/green one. "
             "It's pretty but doesn't match my room. Quite disappointed. Emma"},
    {"id": "m3", "from": "alex.m.buys@example.net", "date": _ts(2, 23, 48), "subject": "URGENT ship all 3 orders today",
     "body": "Ship all three orders TODAY by fastest courier to my agent Global Fwd LLC in Wilmington. "
             "I will pay extra. Do not call, email only."},
    {"id": "m4", "from": "orders@dhl.example", "date": _ts(8, 14, 20), "subject": "Delivered: DHL 4455 2981 07",
     "body": "Your shipment 4455 2981 07 was delivered and signed for by J CARTER."},
    {"id": "m5", "from": "ravi.kapoor@example.sg", "date": _ts(5, 9, 0), "subject": "Bulk order enquiry",
     "body": "Could you quote 40 brass lamps for a hotel project in Singapore?"},
]

JIRA = [
    {"key": "OPS-12", "summary": "Customs paperwork pending for 4 EU shipments", "priority": "High", "status": "In Progress", "assignee": "@priya"},
    {"key": "OPS-15", "summary": "Restock cobalt blue vases (sold out, listing still live)", "priority": "Medium", "status": "To Do", "assignee": "@priya"},
    {"key": "OPS-18", "summary": "Checkout page slow on mobile Safari", "priority": "High", "status": "To Do", "assignee": "@arjun"},
]


def fresh_state() -> dict:
    return {
        "playbook": PLAYBOOK,
        "transactions": _transactions(),
        "disputes": copy.deepcopy(DISPUTES),
        "orders": copy.deepcopy(ORDERS),
        "inbox": copy.deepcopy(INBOX),
        "jira": copy.deepcopy(JIRA),
        "cases": [], "outbox": [], "slack": [], "evidence": [], "offers": [], "accepted": [],
    }
