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
    "repo-atlas-ingestion": {
        "name": "gh_push_atlas_ingestion",
        "description": (
            "Read and push to the atlas-ingestion GitHub repo. Only while grant "
            "{grant_id} is active (expires {expires})."
        ),
    },
    "repo-finance-ledger": {
        "name": "gh_read_finance_ledger",
        "description": (
            "Read the finance-ledger GitHub repo. Only while grant "
            "{grant_id} is active (expires {expires})."
        ),
    },
    "sap-bp-display": {
        "name": "sap_display_bp_1710001",
        "description": (
            "Display Business Partner 1710001 in Customer Master. Only while grant "
            "{grant_id} is active (expires {expires})."
        ),
    },
    "sap-billing-display": {
        "name": "sap_display_billing_northwind",
        "description": (
            "Display the Northwind billing document. Only while grant "
            "{grant_id} is active (expires {expires})."
        ),
    },
    "sap-sales-order-display": {
        "name": "sap_display_sales_order_northwind",
        "description": (
            "Display the Northwind sales order. Only while grant "
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
    seen: set[str] = set()
    for grant in grants:
        if not _is_active(grant, now=now):
            continue
        spec = TOOL_SPECS.get(grant.resource_id)
        if spec is None or spec["name"] in seen:
            continue
        seen.add(spec["name"])
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
