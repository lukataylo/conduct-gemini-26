from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))
sys.path.append(str(ROOT / "agent-runtime"))

from shared.schemas import Grant, Requester  # noqa: E402


@pytest.fixture
def requester() -> Requester:
    return Requester(
        id="u-newhire-1",
        name="Alex Chen",
        role="Software Engineer (new hire)",
        team="data-platform",
        manager_id="u-manager-1",
    )


@pytest.fixture
def grant() -> Grant:
    now = datetime.now(timezone.utc)
    return Grant(
        id="g-1",
        request_id="r-1",
        resource_id="bucket-analytics-raw",
        requester_id="u-newhire-1",
        granted_at=now,
        expires_at=now + timedelta(days=14),
    )
