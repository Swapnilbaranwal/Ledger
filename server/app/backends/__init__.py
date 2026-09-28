"""Pick mock or Swytchcode backend per service.

    BACKEND=mock            # everything mocked (default)
    BACKEND=swytch          # everything live through Swytchcode
    BACKEND_SLACK=swytch    # per-service override, e.g. live Slack + mocked PayPal
"""
from __future__ import annotations

import os
from functools import lru_cache

from . import mock, swytch

_MAP = {
    "paypal": (mock.MockPayPal, swytch.SwyPayPal),
    "notion": (mock.MockNotion, swytch.SwyNotion),
    "gmail": (mock.MockGmail, swytch.SwyGmail),
    "jira": (mock.MockJira, swytch.SwyJira),
    "slack": (mock.MockSlack, swytch.SwySlack),
}


def mode(service: str) -> str:
    return os.getenv(f"BACKEND_{service.upper()}", os.getenv("BACKEND", "mock")).lower()


@lru_cache(maxsize=None)
def get(service: str):
    mock_cls, live_cls = _MAP[service]
    return live_cls() if mode(service) == "swytch" else mock_cls()


def describe() -> dict[str, str]:
    return {s: mode(s) for s in _MAP}
