from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "policy-engine"))
sys.path.append(str(ROOT))

from engine import evaluate_request  # noqa: E402
from escalation import open_case  # noqa: E402
from shared.schemas import (  # noqa: E402
    AccessRequest,
    DecisionType,
    Grant,
    PolicyEvaluationContext,
    RequestHistoryEvent,
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


def test_inactive_requester_hard_denies_everything():
    inactive_requester = requester().model_copy(update={"is_active": False})
    decisions = evaluate_request(
        access_request(requester_override=inactive_requester),
        {"resource-1": resource()},
    )

    assert len(decisions) == 1
    assert decisions[0].resource_id == "all"
    assert decisions[0].decision == DecisionType.AUTO_DENY
    assert "INACTIVE" in decisions[0].reason


def test_stale_hr_heartbeat_hard_denies_everything():
    stale_requester = requester().model_copy(
        update={
            "last_hr_sync": datetime(2026, 9, 18, 10, 59, tzinfo=timezone.utc),
        }
    )
    request = access_request(requester_override=stale_requester)

    decisions = evaluate_request(
        request,
        {"resource-1": resource()},
        now=datetime(2026, 9, 19, 11, 0, tzinfo=timezone.utc),
    )

    assert decisions[0].resource_id == "all"
    assert decisions[0].decision == DecisionType.AUTO_DENY
    assert "heartbeat is stale" in decisions[0].reason


def test_missing_ticket_or_incident_hard_denies_everything():
    decisions = evaluate_request(
        access_request(metadata={}),
        {"resource-1": resource()},
    )

    assert decisions[0].resource_id == "all"
    assert decisions[0].decision == DecisionType.AUTO_DENY
    assert "ticket_id or incident_id is required" in decisions[0].reason


def test_destructive_capability_upgrades_internal_resource_to_critical_escalation():
    decision = evaluate_one(
        access_request(),
        resource(capability="delete", sensitivity=SensitivityTier.INTERNAL),
    )

    assert decision.decision == DecisionType.ESCALATE
    assert "DESTRUCTIVE ACTION DETECTED" in decision.reason
    assert "requires 2 approval" in decision.reason
    assert "security_lead" in decision.required_approval_groups


def test_requesting_more_than_five_resources_escalates_to_engineering_vp():
    requested_ids = [f"resource-{i}" for i in range(6)]
    resources = {resource_id: resource(resource_id=resource_id) for resource_id in requested_ids}

    decisions = evaluate_request(
        access_request(resource_ids=requested_ids),
        resources,
    )

    assert len(decisions) == 1
    assert decisions[0].resource_id == "multiple"
    assert decisions[0].decision == DecisionType.ESCALATE
    assert "Blast radius exceeded" in decisions[0].reason
    assert "VP_ENG" in decisions[0].required_approval_groups


def test_more_than_twenty_active_resources_escalates_to_engineering_vp():
    now = datetime.now(timezone.utc)
    active_grants = [
        Grant(
            id=f"grant-{i}",
            request_id=f"old-req-{i}",
            resource_id=f"active-resource-{i}",
            requester_id="u-requester",
            expires_at=now + timedelta(days=1),
        )
        for i in range(20)
    ]

    decisions = evaluate_request(
        access_request(),
        {"resource-1": resource()},
        active_grants=active_grants,
    )

    assert decisions[0].resource_id == "multiple"
    assert decisions[0].decision == DecisionType.ESCALATE
    assert "21 active resources" in decisions[0].reason
    assert "VP_ENG" in decisions[0].required_approval_groups


def test_cisco_scenario_inactive_user_returns_hard_deny():
    inactive_requester = requester().model_copy(update={"is_active": False})

    decisions = evaluate_request(
        access_request(requester_override=inactive_requester),
        {"resource-1": resource(capability="delete")},
    )

    assert decisions[0].decision == DecisionType.AUTO_DENY
    assert decisions[0].resource_id == "all"
    assert "INACTIVE" in decisions[0].reason


def test_capitalone_scenario_fifty_buckets_triggers_blast_radius_escalation():
    requested_ids = [f"s3-bucket-{i}" for i in range(50)]
    resources = {resource_id: resource(resource_id=resource_id) for resource_id in requested_ids}

    decisions = evaluate_request(
        access_request(resource_ids=requested_ids),
        resources,
    )

    assert len(decisions) == 1
    assert decisions[0].decision == DecisionType.ESCALATE
    assert decisions[0].resource_id == "multiple"
    assert "CapitalOne-Risk" in decisions[0].reason
    assert "VP_ENG" in decisions[0].required_approval_groups


def test_velocity_scenario_on_call_engineer_gets_instant_database_access():
    on_call_requester = requester().model_copy(update={"is_on_call": True})

    decision = evaluate_one(
        access_request(
            requester_override=on_call_requester,
            metadata={"incident_id": "PD-1234"},
        ),
        resource(
            sensitivity=SensitivityTier.CRITICAL,
            capability="read",
        ),
    )

    assert decision.decision == DecisionType.AUTO_GRANT
    assert decision.ttl_hours == 4
    assert "On-call engineer" in decision.reason


def test_ramesh_rule_delete_internal_bucket_escalates_to_critical():
    decision = evaluate_one(
        access_request(),
        resource(capability="delete", sensitivity=SensitivityTier.INTERNAL),
    )

    assert decision.decision == DecisionType.ESCALATE
    assert "Ramesh-Rule-01" in decision.reason
    assert "requires 2 approval" in decision.reason
    assert "sec_ops" in decision.required_approval_groups
    assert "owner" in decision.required_approval_groups


def test_peer_signal_flags_outlier_escalations_for_approval_card():
    decision = evaluate_request(
        access_request(requester_team="data-platform"),
        {"resource-1": resource(sensitivity=SensitivityTier.RESTRICTED)},
        team_size_by_team={"data-platform": 20},
    )[0]

    assert decision.decision == DecisionType.ESCALATE
    assert decision.metadata["peer_access_ratio"] == 0
    assert decision.metadata["peer_warning"] == "Warning: Outlier Request"


def test_github_new_hire_critical_repo_escalates_to_security_lead():
    new_hire = requester().model_copy(update={"tenure_days": 30})

    decision = evaluate_one(
        access_request(requester_override=new_hire),
        resource(
            resource_type=ResourceType.GITHUB_REPO,
            sensitivity=SensitivityTier.INTERNAL,
            capability="read",
            metadata={"is_critical": True},
        ),
    )

    assert decision.decision == DecisionType.ESCALATE
    assert "GitHub-Tenure-01" in decision.reason
    assert "security_lead" in decision.required_approval_groups


def test_github_admin_or_main_branch_is_hard_denied():
    admin_decision = evaluate_one(
        access_request(),
        resource(resource_type=ResourceType.GITHUB_REPO, capability="ADMIN"),
    )
    main_branch_decision = evaluate_one(
        access_request(),
        resource(resource_type=ResourceType.GITHUB_REPO, target="main_branch"),
    )

    assert admin_decision.decision == DecisionType.AUTO_DENY
    assert main_branch_decision.decision == DecisionType.AUTO_DENY
    assert "manual-only" in admin_decision.reason


def test_bot_scraper_agent_asking_for_ten_databases_is_denied():
    agent = requester().model_copy(update={"identity_type": "agent"})
    requested_ids = [f"db-{i}" for i in range(10)]
    resources = {
        resource_id: resource(
            resource_id=resource_id,
            resource_type=ResourceType.CLOUD_SQL_INSTANCE,
            sensitivity=SensitivityTier.RESTRICTED,
        )
        for resource_id in requested_ids
    }

    decisions = evaluate_request(
        access_request(requester_override=agent, resource_ids=requested_ids),
        resources,
    )

    assert len(decisions) == 1
    assert decisions[0].decision == DecisionType.AUTO_DENY
    assert "Bot-Scraper-01" in decisions[0].reason


def test_powerbi_view_auto_grants_but_export_escalates_to_data_steward():
    view_decision = evaluate_one(
        access_request(),
        resource(
            resource_type=ResourceType.POWERBI_DATASET,
            capability="VIEW",
            metadata={"has_pii": True},
        ),
    )
    export_decision = evaluate_one(
        access_request(),
        resource(
            resource_type=ResourceType.POWERBI_DATASET,
            capability="EXPORT",
            metadata={"has_pii": True},
        ),
    )

    assert view_decision.decision == DecisionType.AUTO_GRANT
    assert view_decision.metadata["restriction"] == "DISABLE_EXPORT"
    assert export_decision.decision == DecisionType.ESCALATE
    assert "data_steward" in export_decision.required_approval_groups
    assert export_decision.metadata["restriction"] == "DISABLE_EXPORT"


def test_persistent_attacker_moves_from_hard_lock_to_soc_alert():
    now = datetime.now(timezone.utc)
    denied_history = [
        RequestHistoryEvent(
            requester_id="u-requester",
            resource_id="resource-1",
            decision=DecisionType.AUTO_DENY,
            reason="previous deny",
            timestamp=now - timedelta(hours=i + 1),
        )
        for i in range(3)
    ]

    locked = evaluate_request(
        access_request(),
        {"resource-1": resource()},
        request_history=denied_history,
        now=now,
    )[0]
    soc_alert = evaluate_request(
        access_request(),
        {"resource-1": resource()},
        request_history=[
            *denied_history,
            RequestHistoryEvent(
                requester_id="u-requester",
                resource_id="resource-1",
                decision=DecisionType.AUTO_DENY,
                timestamp=now - timedelta(minutes=10),
            ),
        ],
        now=now,
    )[0]

    assert locked.decision == DecisionType.AUTO_DENY
    assert "Circuit Breaker Active" in locked.reason
    assert soc_alert.decision == DecisionType.ESCALATE
    assert "soc" in soc_alert.required_approval_groups


def test_cross_pollination_data_correlation_risk_escalates():
    active_grants = [
        Grant(
            id="grant-hr",
            request_id="old",
            resource_id="hr-payroll",
            requester_id="u-requester",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
    ]

    decision = evaluate_one(
        access_request(),
        resource(metadata={"correlation_risk_with": ["hr-payroll"]}),
    )
    decision_with_grant = evaluate_request(
        access_request(),
        {
            "resource-1": resource(
                metadata={"correlation_risk_with": ["hr-payroll"]},
            )
        },
        active_grants=active_grants,
    )[0]

    assert decision.decision == DecisionType.AUTO_GRANT
    assert decision_with_grant.decision == DecisionType.ESCALATE
    assert "Potential Data Correlation Risk" in decision_with_grant.reason


def test_escalation_case_includes_evidence_card_fields_and_downgrade():
    decision = evaluate_one(
        access_request(requested_duration_days=14),
        resource(resource_type=ResourceType.GITHUB_REPO, capability="ADMIN"),
    )

    case = open_case(
        decision,
        case_id="case-1",
        approver_ids=["approver-1"],
        requester_id="u-requester",
        requested_duration_days=14,
        request=access_request(requested_duration_days=14),
        resource=resource(resource_type=ResourceType.GITHUB_REPO, capability="ADMIN"),
        now=datetime.now(timezone.utc),
    )

    assert case.policy_violation
    assert case.risk_score == "high"
    assert case.suggested_downgrade == "Grant READ for 4 hours"


def test_out_of_office_contractor_denied_for_warehouse_iot_control():
    contractor = requester().model_copy(update={"type": "SEASONAL_CONTRACTOR"})
    context = PolicyEvaluationContext(
        requester_location={"lat": 51.5074, "lon": -0.1278, "label": "home"},
    )

    decision = evaluate_request(
        access_request(requester_override=contractor),
        {
            "resource-1": resource(
                resource_type=ResourceType.WMS_IOT,
                category="WMS_IOT",
                metadata={"geofence_center": {"lat": 51.5000, "lon": -0.1000}},
            )
        },
        context=context,
    )[0]

    assert decision.decision == DecisionType.AUTO_DENY
    assert "Physical presence required" in decision.reason
    assert decision.metadata["policy_violation"] == "Warehouse Geofence"


def test_earnings_quiet_period_downgrades_write_and_escalates_to_cfo():
    context = PolicyEvaluationContext(
        current_date=datetime(2026, 9, 19, 12, tzinfo=timezone.utc),
        company_calendar={
            "quiet_period": [
                {
                    "start": "2026-09-01T00:00:00Z",
                    "end": "2026-09-30T23:59:59Z",
                }
            ]
        },
    )

    decision = evaluate_request(
        access_request(),
        {
            "resource-1": resource(
                surface="FINANCE_PROD",
                capability="write",
                sensitivity=SensitivityTier.RESTRICTED,
            )
        },
        context=context,
    )[0]

    assert decision.decision == DecisionType.ESCALATE
    assert "SOX Compliance" in decision.reason
    assert "cfo" in decision.required_approval_groups
    assert decision.metadata["downgraded_capability"] == "read"
    assert "SOX-404" in decision.metadata["compliance_checked"]


def test_support_impersonation_blocks_ticket_target_mismatch():
    context = PolicyEvaluationContext(
        external_signals={
            "zendesk": {
                "ZD-123": {"requester_email": "customer-a@example.com"}
            }
        }
    )

    decision = evaluate_request(
        access_request(
            metadata={
                "ticket_id": "ZD-123",
                "target_user_email": "customer-b@example.com",
            }
        ),
        {
            "resource-1": resource(
                resource_type=ResourceType.IMPERSONATION_TOOL,
                metadata={"has_pii": True},
            )
        },
        context=context,
    )[0]

    assert decision.decision == DecisionType.AUTO_DENY
    assert "Ticket requester does not match target user" in decision.reason
    assert decision.metadata["policy_violation"] == "Support Impersonation Mismatch"
    assert "GDPR-Art-32" in decision.metadata["compliance_checked"]


def test_payment_rail_requires_witness_session():
    decision = evaluate_request(
        access_request(),
        {"resource-1": resource(resource_type=ResourceType.PAYMENT_RAIL)},
    )[0]

    assert decision.decision == DecisionType.WITNESS_REQUIRED
    assert decision.metadata["witness_required"] is True
    assert "witness" in decision.required_approval_groups
    assert "PCI-DSS-3.2" in decision.metadata["compliance_checked"]


def test_build_pipeline_critical_vulnerability_escalates_to_security_architect():
    context = PolicyEvaluationContext(
        current_date=datetime(2026, 9, 19, 12, tzinfo=timezone.utc),
        external_signals={
            "security_scans": {
                "snyk_score": "FAIL",
                "findings": [
                    {
                        "requester_id": "u-requester",
                        "severity": "Critical Vulnerability",
                        "timestamp": "2026-09-19T10:30:00Z",
                        "tool": "Snyk",
                    }
                ],
            }
        },
    )

    decision = evaluate_request(
        access_request(),
        {
            "resource-1": resource(
                resource_type=ResourceType.BUILD_PIPELINE,
                surface="BUILD_PIPELINE",
            )
        },
        context=context,
    )[0]

    assert decision.decision == DecisionType.ESCALATE
    assert "CI/CD Safety Sync" in decision.reason
    assert "security_architect" in decision.required_approval_groups
    assert decision.metadata["scan_report"]["tool"] == "Snyk"


def test_secret_harvesting_threshold_triggers_anomaly_alarm():
    now = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)
    active_grants = [
        Grant(
            id=f"grant-secret-{i}",
            request_id=f"req-secret-{i}",
            resource_id=f"secret-{i}",
            requester_id="u-requester",
            granted_at=now - timedelta(minutes=10),
            expires_at=now + timedelta(hours=1),
        )
        for i in range(3)
    ]

    decision = evaluate_request(
        access_request(resource_ids=["secret-4"]),
        {"secret-4": resource(resource_id="secret-4", resource_type=ResourceType.VAULT_SECRET)},
        active_grants=active_grants,
        context=PolicyEvaluationContext(current_date=now),
    )[0]

    assert decision.decision == DecisionType.AUTO_DENY
    assert "Potential secret harvesting" in decision.reason
    assert decision.metadata["anomaly_alarm"] is True


def test_seasonal_contractor_auto_grant_is_capped_to_thirty_days_and_no_renew():
    contractor = requester().model_copy(update={"type": "SEASONAL_CONTRACTOR"})

    decision = evaluate_request(
        access_request(
            requester_override=contractor,
            requested_duration_days=90,
            metadata={"ticket_id": "JIRA-1234"},
        ),
        {"resource-1": resource()},
    )[0]

    assert decision.decision == DecisionType.AUTO_GRANT
    assert decision.ttl_hours <= 30 * 24
    assert decision.metadata["renew_access_disabled"] is True


def test_sap_customer_directory_and_payroll_are_auto_denied():
    directory = evaluate_one(
        access_request(resource_ids=["sap-customer-directory"]),
        resource(
            resource_id="sap-customer-directory",
            resource_type=ResourceType.SAP_CUSTOMER_DIRECTORY,
            owning_team="finance",
            sensitivity=SensitivityTier.CRITICAL,
            capability="export",
        ),
    )
    payroll = evaluate_one(
        access_request(resource_ids=["sap-hr-payroll"]),
        resource(
            resource_id="sap-hr-payroll",
            resource_type=ResourceType.SAP_HR_PAYROLL,
            owning_team="finance",
            sensitivity=SensitivityTier.CRITICAL,
            capability="admin",
        ),
    )

    assert directory.decision == DecisionType.AUTO_DENY
    assert payroll.decision == DecisionType.AUTO_DENY
    assert "Conduct-SAP-01" in directory.reason
    assert "Conduct-SAP-01" in payroll.reason


def test_sap_business_partner_restricted_cross_team_escalates():
    decision = evaluate_one(
        access_request(requester_team="data-platform", resource_ids=["sap-bp-display"]),
        resource(
            resource_id="sap-bp-display",
            resource_type=ResourceType.SAP_BUSINESS_PARTNER,
            owning_team="finance",
            sensitivity=SensitivityTier.RESTRICTED,
            capability="read",
        ),
    )

    assert decision.decision == DecisionType.ESCALATE
    assert "Cross-team" in decision.reason


def test_sap_sales_order_same_team_internal_auto_grants():
    decision = evaluate_one(
        access_request(requester_team="data-platform", resource_ids=["sap-sales-order-display"]),
        resource(
            resource_id="sap-sales-order-display",
            resource_type=ResourceType.SAP_SALES_ORDER,
            owning_team="data-platform",
            sensitivity=SensitivityTier.INTERNAL,
            capability="read",
        ),
    )

    assert decision.decision == DecisionType.AUTO_GRANT
