"""Tests always run against the mock world, even when .env points services at live Swytchcode.
Set before app import: load_dotenv() never overrides variables that already exist."""
import os

for _service in ("PAYPAL", "NOTION", "GMAIL", "JIRA", "SLACK"):
    os.environ[f"BACKEND_{_service}"] = "mock"
os.environ["BACKEND"] = "mock"

import tempfile  # noqa: E402

import pytest  # noqa: E402

os.environ["LEDGER_MEMORY_PATH"] = os.path.join(tempfile.mkdtemp(), "memory.json")


@pytest.fixture(autouse=True)
def _fresh_memory():
    from app import memory
    memory.reset()
