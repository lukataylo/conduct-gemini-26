from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "policy-engine"))
sys.path.append(str(ROOT))

from engine import evaluate_request  # noqa: E402
from shared.schemas import (  # noqa: E402
    AccessRequest,
    DecisionType,
    Requester,
    Resource,
    ResourceType,
    SensitivityTier,
)


def requester(team: str = "data-platform") -> Requester:
    return Requester(
        id="u-requester",
        name="Alex Chen",
        role="Software Engineer",
        team=team,
        manager_id="u-manager",
    )


def resource(
    *,
    sensitivity: SensitivityTier = SensitivityTier.INTERNAL,
    owning_team: str = "data-platform",
    resource_id: str = "resource-1",
    capability: str = "read",
    resource_type: ResourceType = ResourceType.GCS_BUCKET,
    target: str | None = None,
    metadata: dict | None = None,
    surface: str | None = None,
    category: str | None = None,
) -> Resource:
    return Resource(
        id=resource_id,
        name="analytics-raw",
        type=resource_type,
        owning_team=owning_team,
        sensitivity=sensitivity,
        project="atlas-migration",
        capability=capability,
        target=target,
        surface=surface,
        category=category,
        metadata=metadata or {},
    )


def access_request(
    *,
    requester_team: str = "data-platform",
    requested_duration_days: int = 1,
    resource_ids: list[str] | None = None,
    metadata: dict | None = None,
    requester_override: Requester | None = None,
) -> AccessRequest:
    return AccessRequest(
        id="req-1",
        requester=requester_override or requester(team=requester_team),
        task_description="Build the ingestion pipeline for Project Atlas",
        project="atlas-migration",
        resource_ids=resource_ids or ["resource-1"],
        requested_duration_days=requested_duration_days,
        metadata=metadata if metadata is not None else {"ticket_id": "JIRA-1234"},
    )


def evaluate_one(request: AccessRequest, target: Resource):
    return evaluate_request(request, {target.id: target})[0]


def test_gcp_same_team_internal_bucket_tags_platform_gcp():
    decision = evaluate_one(access_request(), resource())

    assert decision.decision == DecisionType.AUTO_GRANT
    assert decision.metadata["platform"] == "gcp"


def test_gcp_finance_cross_team_escalates_and_tags_platform_gcp():
    decision = evaluate_one(
        access_request(requester_team="data-platform"),
        resource(
            resource_type=ResourceType.BIGQUERY_DATASET,
            sensitivity=SensitivityTier.RESTRICTED,
            owning_team="finance",
        ),
    )

    assert decision.decision == DecisionType.ESCALATE
    assert decision.metadata["platform"] == "gcp"


def test_sap_directory_still_auto_denies_and_tags_platform_sap():
    decision = evaluate_one(
        access_request(resource_ids=["sap-customer-directory"]),
        resource(
            resource_id="sap-customer-directory",
            resource_type=ResourceType.SAP_CUSTOMER_DIRECTORY,
            owning_team="finance",
            sensitivity=SensitivityTier.CRITICAL,
            capability="export",
        ),
    )

    assert decision.decision == DecisionType.AUTO_DENY
    assert "Conduct-SAP-01" in decision.reason
    assert decision.metadata["platform"] == "sap"


def test_sap_business_partner_company_2000_is_auto_denied():
    decision = evaluate_one(
        access_request(resource_ids=["sap-bp-display"]),
        resource(
            resource_id="sap-bp-display",
            resource_type=ResourceType.SAP_BUSINESS_PARTNER,
            owning_team="finance",
            sensitivity=SensitivityTier.RESTRICTED,
            capability="read",
            metadata={"company_code": "2000"},
        ),
    )

    assert decision.decision == DecisionType.AUTO_DENY
    assert "2000" in decision.reason
