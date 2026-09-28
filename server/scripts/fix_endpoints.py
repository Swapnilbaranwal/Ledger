"""Swytchcode's catalog ships most bundles with sandbox_endpoint=http://localhost.
This points them at real hosts. Re-run after any `swy get`.
    python scripts/fix_endpoints.py [https://yoursite.atlassian.net]"""
import json, os, sys
P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".swytchcode/integrations/manifest.json")
jira = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("JIRA_SITE_URL", "")).rstrip("/")
m = json.load(open(P))
for k, v in m.items():
    if k.startswith("PayPal."):
        v["sandbox_endpoint"], v["production_endpoint"] = "https://api-m.sandbox.paypal.com", "https://api-m.paypal.com"
    elif k.startswith("Jira.") and jira and "your-site" not in jira:
        v["sandbox_endpoint"] = v["production_endpoint"] = jira
    elif v.get("sandbox_endpoint", "").startswith("http://localhost") and v.get("production_endpoint", "").startswith("https://") \
            and "your-domain" not in v["production_endpoint"]:
        v["sandbox_endpoint"] = v["production_endpoint"]   # Gmail/Notion/Slack: your test workspace is the sandbox
json.dump(m, open(P, "w"), indent=2)
for k, v in m.items():
    print(f"{k:50} {v['sandbox_endpoint']}")
