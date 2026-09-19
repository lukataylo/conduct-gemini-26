"""
The concrete scenario the whole demo runs on: a new hire joining "Project Atlas", a
cross-team data migration. Deliberately picked so the golden path produces exactly one
auto-grant and one escalation from a single request (see root README's golden path).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from shared.schemas import Requester, Resource, ResourceType, SensitivityTier  # noqa: E402

TEAMS = ["data-platform", "growth", "finance"]

REQUESTER = Requester(
    id="u-newhire-1",
    name="Alex Chen",
    role="Software Engineer (new hire)",
    team="data-platform",
    manager_id="u-manager-1",
)

MANAGER = Requester(
    id="u-manager-1",
    name="Priya Nair",
    role="Engineering Manager",
    team="data-platform",
)

FINANCE_OWNER = Requester(
    id="u-finance-owner-1",
    name="Jordan Lee",
    role="Finance Data Owner",
    team="finance",
)

RESOURCES: dict[str, Resource] = {
    r.id: r
    for r in [
        Resource(
            id="bucket-analytics-raw",
            name="analytics-raw",
            type=ResourceType.GCS_BUCKET,
            owning_team="data-platform",
            sensitivity=SensitivityTier.INTERNAL,
            project="atlas-migration",
            capability="write",
        ),
        Resource(
            id="bq-project-x-finance",
            name="project-x-finance",
            type=ResourceType.BIGQUERY_DATASET,
            owning_team="finance",
            sensitivity=SensitivityTier.RESTRICTED,
            project="atlas-migration",
        ),
        Resource(
            id="sql-prod-primary",
            name="prod-primary",
            type=ResourceType.CLOUD_SQL_INSTANCE,
            owning_team="data-platform",
            sensitivity=SensitivityTier.CRITICAL,
            project="atlas-migration",
        ),
        Resource(
            id="repo-atlas-ingestion",
            name="atlas-ingestion",
            type=ResourceType.GITHUB_REPO,
            owning_team="data-platform",
            sensitivity=SensitivityTier.INTERNAL,
            project="atlas-migration",
            capability="write",
        ),
        Resource(
            id="repo-finance-ledger",
            name="finance-ledger",
            type=ResourceType.GITHUB_REPO,
            owning_team="finance",
            sensitivity=SensitivityTier.RESTRICTED,
            project="atlas-migration",
        ),
        Resource(
            id="sap-bp-display",
            name="Customer Master · Northwind 1710001",
            type=ResourceType.SAP_BUSINESS_PARTNER,
            owning_team="finance",
            sensitivity=SensitivityTier.RESTRICTED,
            project="atlas-migration",
            capability="read",
            metadata={
                "company_code": "1000",
                "customer_id": "1710001",
                "role": "SAP_SD_CUST_DISPLAY",
                "activity": "03",
            },
        ),
        Resource(
            id="sap-billing-display",
            name="Billing · Northwind 90001234",
            type=ResourceType.SAP_BILLING_DOCUMENT,
            owning_team="finance",
            sensitivity=SensitivityTier.RESTRICTED,
            project="atlas-migration",
            capability="read",
            metadata={
                "company_code": "1000",
                "customer_id": "1710001",
                "role": "SAP_SD_BILL_DISPLAY",
                "activity": "03",
            },
        ),
        Resource(
            id="sap-sales-order-display",
            name="Sales Order · 4500008123",
            type=ResourceType.SAP_SALES_ORDER,
            owning_team="data-platform",
            sensitivity=SensitivityTier.INTERNAL,
            project="atlas-migration",
            capability="read",
            metadata={
                "company_code": "1000",
                "customer_id": "1710001",
                "role": "SAP_SD_SO_DISPLAY",
                "activity": "03",
            },
        ),
        Resource(
            id="sap-customer-directory",
            name="Customer Directory / Export",
            type=ResourceType.SAP_CUSTOMER_DIRECTORY,
            owning_team="finance",
            sensitivity=SensitivityTier.CRITICAL,
            project="atlas-migration",
            capability="export",
            metadata={
                "company_code": "1000",
                "role": "SAP_SD_CUST_EXPORT",
                "activity": "16",
            },
        ),
        Resource(
            id="sap-hr-payroll",
            name="Employee Payroll",
            type=ResourceType.SAP_HR_PAYROLL,
            owning_team="finance",
            sensitivity=SensitivityTier.CRITICAL,
            project="atlas-migration",
            capability="admin",
            metadata={"locked": True},
        ),
    ]
}

# resource_id -> approver requester ids, used by backend-api to fill in
# PolicyDecision.required_approver_ids when policy-engine escalates
APPROVERS: dict[str, list[str]] = {
    "bucket-analytics-raw": [MANAGER.id],
    "bq-project-x-finance": [FINANCE_OWNER.id, MANAGER.id],  # cross-team: both sides
    "sql-prod-primary": [MANAGER.id, FINANCE_OWNER.id],
    "repo-atlas-ingestion": [MANAGER.id],
    "repo-finance-ledger": [FINANCE_OWNER.id, MANAGER.id],
    "multiple": [MANAGER.id, FINANCE_OWNER.id],  # blast-radius escalations (engine emits resource_id="multiple")
    "sap-bp-display": [FINANCE_OWNER.id, MANAGER.id],
    "sap-billing-display": [FINANCE_OWNER.id, MANAGER.id],
    "sap-sales-order-display": [MANAGER.id],
    "sap-customer-directory": [FINANCE_OWNER.id, MANAGER.id],
    "sap-hr-payroll": [FINANCE_OWNER.id, MANAGER.id],
}

# The natural-language request agent-runtime parses at the start of the demo
GOLDEN_PATH_REQUEST_TEXT = (
    "I need access to the analytics-raw GCS bucket and the project-x-finance "
    "BigQuery dataset to build the ingestion pipeline for Project Atlas, "
    "done by Nov 15."
)
