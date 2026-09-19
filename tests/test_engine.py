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
) -> Resource:
    return Resource(
        id="resource-1",
        name="analytics-raw",
        type=ResourceType.GCS_BUCKET,
        owning_team=owning_team,
        sensitivity=sensitivity,
        project="atlas-migration",
    )


def access_request(
    *,
    requester_team: str = "data-platform",
    requested_duration_days: int = 1,
) -> AccessRequest:
    return AccessRequest(
        id="req-1",
        requester=requester(team=requester_team),
        task_description="Build the ingestion pipeline for Project Atlas",
        project="atlas-migration",
        resource_ids=["resource-1"],
        requested_duration_days=requested_duration_days,
    )


def evaluate_one(request: AccessRequest, target: Resource):
    return evaluate_request(request, {target.id: target})[0]


def test_same_team_internal_resource_auto_grants():
    decision = evaluate_one(access_request(), resource())

    assert decision.decision == DecisionType.AUTO_GRANT
    assert decision.resource_id == "resource-1"


def test_cross_team_request_escalates():
    decision = evaluate_one(
        access_request(requester_team="data-platform"),
        resource(sensitivity=SensitivityTier.RESTRICTED, owning_team="finance"),
    )

    assert decision.decision == DecisionType.ESCALATE
    assert "Cross-team" in decision.reason


def test_over_duration_request_escalates():
    decision = evaluate_one(
        access_request(requested_duration_days=31),
        resource(sensitivity=SensitivityTier.INTERNAL),
    )

    assert decision.decision == DecisionType.ESCALATE
    assert "exceeds auto-grant limit" in decision.reason


def test_critical_tier_always_escalates():
    decision = evaluate_one(
        access_request(requested_duration_days=1),
        resource(sensitivity=SensitivityTier.CRITICAL),
    )

    assert decision.decision == DecisionType.ESCALATE
    assert "critical tier always escalates" in decision.reason
