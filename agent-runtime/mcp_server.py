"""Scoped MCP tool list derived from already-issued grants.

Models never grant. sql-prod-primary is never exposed even if a grant exists.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from shared.schemas import Grant  # noqa: E402

TOOL_SPECS: dict[str, dict[str, str]] = {
    "bucket-analytics-raw": {
        "name": "gcs_list_analytics_raw",
        "description": (
            "List objects in analytics-raw. Only while grant {grant_id} "
            "is active (expires {expires})."
        ),
    },
    "bq-project-x-finance": {
        "name": "bq_query_project_x_finance",
        "description": (
            "Run a read-only query on project-x-finance. Only while grant "
            "{grant_id} is active (expires {expires})."
        ),
    },
}


def _is_active(grant: Grant, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if grant.revoked:
        return False
    expires = grant.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > now


def tools_for_grants(grants: list[Grant], *, now: datetime | None = None) -> list[dict]:
    """Return MCP-shaped tools for active, allowlisted grants only."""
    tools: list[dict] = []
    for grant in grants:
        if not _is_active(grant, now=now):
            continue
        spec = TOOL_SPECS.get(grant.resource_id)
        if spec is None:
            continue
        tools.append(
            {
                "name": spec["name"],
                "description": spec["description"].format(
                    grant_id=grant.id,
                    expires=grant.expires_at.isoformat(),
                ),
                "grant_id": grant.id,
                "resource_id": grant.resource_id,
            }
        )
    return tools
