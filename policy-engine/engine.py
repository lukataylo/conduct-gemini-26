"""
Deterministic policy engine.

This is the security-critical path: no LLM in here. Gemini/Claude parse requests and
explain decisions elsewhere (agent-runtime); this module only ever sees typed input and
returns typed, deterministic output so every decision is reproducible and auditable.
"""
from __future__ import annotations

import sys
from math import asin, cos, radians, sin, sqrt
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

sys.path.append(str(Path(__file__).resolve().parents[1]))

from shared.schemas import (  # noqa: E402
    AccessRequest,
    AuthType,
    DecisionType,
    Grant,
    PolicyDecision,
    PolicyEvaluationContext,
    PolicyRule,
    RequestHistoryEvent,
    Resource,
    ResourceType,
    RevocationAction,
    SensitivityTier,
)

PHISHING_RESISTANT_AUTH = {
    AuthType.FIDO2_MFA,
    AuthType.PASSKEY,
    AuthType.HARDWARE_TOKEN,
}

DESTRUCTIVE_ACTIONS = {"delete", "drop", "terminate", "iam_change"}
DESTRUCTIVE_CAPABILITIES = DESTRUCTIVE_ACTIONS
MAX_BLAST_RADIUS = 5
MAX_ACTIVE_RESOURCES = 20
HR_SYNC_MAX_AGE = timedelta(hours=24)
MANAGER_GROUP = "manager"
OWNER_GROUP = "owner"
SEC_OPS_GROUP = "sec_ops"
SECURITY_LEAD_GROUP = "security_lead"
ENGINEERING_VP_GROUP = "VP_ENG"
DATA_STEWARD_GROUP = "data_steward"
SOC_GROUP = "soc"
CFO_GROUP = "cfo"
SECURITY_ARCHITECT_GROUP = "security_architect"
WITNESS_GROUP = "witness"
ANOMALY_ALARM_GROUP = "anomaly_alarm"

DEFAULT_POLICY = PolicyRule(
    id="default",
    description="Default hackathon-demo policy",
    max_auto_grant_duration_days={
        SensitivityTier.PUBLIC: 90,
        SensitivityTier.INTERNAL: 30,
        SensitivityTier.RESTRICTED: 7,
        SensitivityTier.CRITICAL: 0,  # critical always escalates, see always_escalate_tiers
    },
)


def evaluate_request(
    request: AccessRequest,
    resources: dict[str, Resource],
    policy: PolicyRule = DEFAULT_POLICY,
    active_grants: Iterable[Grant] | None = None,
    request_history: Iterable[RequestHistoryEvent | dict] | None = None,
    context: PolicyEvaluationContext | dict | None = None,
    team_size_by_team: dict[str, int] | None = None,
    now: datetime | None = None,
) -> list[PolicyDecision]:
    """Evaluate one AccessRequest against every resource it names.

    Returns one PolicyDecision per resource_id — a single request can be granted on
    some resources and escalated on others (see README golden path: bucket auto-grants,
    dataset escalates, from the same request).
    """
    eval_context = _evaluation_context(context, request.created_at)
    now = now or eval_context.current_date or request.created_at

    global_deny_reason = _global_hard_deny_reason(request, now)
    if global_deny_reason is not None:
        return [_deny(request, "all", global_deny_reason)]

    agent_deny_reason = _agent_deny_reason(request, active_grants)
    if agent_deny_reason is not None:
        return [_deny(request, "all", agent_deny_reason)]

    circuit_breaker = _circuit_breaker_decision(request, request_history, now)
    if circuit_breaker is not None:
        return [circuit_breaker]

    blast_radius_reason = _blast_radius_reason(request, active_grants)
    if blast_radius_reason is not None:
        return [
            PolicyDecision(
                request_id=request.id,
                resource_id="multiple",
                decision=DecisionType.ESCALATE,
                reason=blast_radius_reason,
                required_approval_groups=[ENGINEERING_VP_GROUP],
                audit_tags=["blast_radius_exceeded"],
                metadata={"risk_score": "high", "policy_violation": "Blast Radius"},
            )
        ]

    decisions: list[PolicyDecision] = []
    for resource_id in request.resource_ids:
        resource = resources.get(resource_id)
        if resource is None:
            decisions.append(
                PolicyDecision(
                    request_id=request.id,
                    resource_id=resource_id,
                    decision=DecisionType.AUTO_DENY,
                    reason=f"Unknown resource '{resource_id}'",
                )
            )
            continue

        decisions.append(
            _evaluate_single(
                request,
                resource,
                policy,
                active_grants=active_grants,
                eval_context=eval_context,
                team_size_by_team=team_size_by_team,
            )
        )

    return decisions


def review_active_grants(
    active_grants: Iterable[Grant],
    resources: dict[str, Resource],
    context: PolicyEvaluationContext | dict,
) -> list[RevocationAction]:
    """Continuously review grants against live business/security signals.

    Pure function: callers pass HR, ticket, incident, calendar, and location state in
    `context`; this function only returns the revocations that should be executed.
    """
    eval_context = _evaluation_context(context, datetime.now(timezone.utc))
    revocations: list[RevocationAction] = []

    for grant in active_grants:
        if grant.revoked:
            continue

        identity_action = _identity_revocation(grant, eval_context)
        if identity_action is not None:
            revocations.append(identity_action)
            continue

        ticket_action = _justification_revocation(grant, eval_context)
        if ticket_action is not None:
            revocations.append(ticket_action)
            continue

        resource = resources.get(grant.resource_id)
        if resource is None:
            continue

        finance_action = _finance_reaper_revocation(grant, resource, eval_context)
        if finance_action is not None:
            revocations.append(finance_action)
            continue

        geofence_action = _geofence_reaper_revocation(grant, resource, eval_context)
        if geofence_action is not None:
            revocations.append(geofence_action)

    return revocations


def _evaluate_single(
    request: AccessRequest,
    resource: Resource,
    policy: PolicyRule,
    *,
    active_grants: Iterable[Grant] | None = None,
    eval_context: PolicyEvaluationContext | None = None,
    team_size_by_team: dict[str, int] | None = None,
) -> PolicyDecision:
    hard_deny_reason = _per_resource_hard_deny_reason(request)
    if hard_deny_reason is not None:
        return _deny(request, resource.id, hard_deny_reason)

    auth_decision = _authentication_decision(request, resource)
    if auth_decision is not None:
        return auth_decision

    if resource.project != request.project:
        return _deny(
            request,
            resource.id,
            f"Resource project '{resource.project}' is outside requested project '{request.project}'",
        )

    tier, destructive_reason = _effective_tier(resource)
    cross_team = resource.owning_team != request.requester.team
    peer_metadata = _peer_metadata(request, resource, active_grants, team_size_by_team)
    shield_decision = _industry_shield_decision(
        request,
        resource,
        policy,
        eval_context or _evaluation_context(None, request.created_at),
        active_grants=active_grants,
        peer_metadata=peer_metadata,
    )
    if shield_decision is not None:
        return shield_decision

    correlation_decision = _correlation_risk_decision(
        request,
        resource,
        resources=None,
        active_grants=active_grants,
        peer_metadata=peer_metadata,
        policy=policy,
    )
    if correlation_decision is not None:
        return correlation_decision

    surface_decision = _surface_decision(
        request,
        resource,
        policy,
        active_grants=active_grants,
        peer_metadata=peer_metadata,
    )
    if surface_decision is not None:
        return surface_decision

    if request.requester.is_on_call and _incident_id(request):
        return _grant(
            request,
            resource,
            reason="Auto-Approved: On-call engineer responding to active incident (Velocity-Benefit-05).",
            ttl_hours=4,
            metadata=peer_metadata,
        )

    if tier in policy.always_escalate_tiers:
        reason = destructive_reason or f"{tier.value} tier always escalates"
        return _escalate(
            request,
            resource,
            policy,
            reason=reason,
            effective_tier=tier,
            required_approval_groups=(
                [SEC_OPS_GROUP, OWNER_GROUP, SECURITY_LEAD_GROUP]
                if destructive_reason
                else [SEC_OPS_GROUP, OWNER_GROUP]
            ),
            metadata=peer_metadata,
        )

    max_days = policy.max_auto_grant_duration_days.get(tier, 0)
    requested_days = _effective_requested_duration_days(request)
    if requested_days > max_days:
        return _escalate(
            request,
            resource,
            policy,
            reason=(
                f"Requested {requested_days}d exceeds auto-grant limit "
                f"of {max_days}d for {tier.value} tier"
            ),
            metadata=peer_metadata,
        )

    if cross_team and policy.cross_team_requires_all_owners:
        return _escalate(
            request,
            resource,
            policy,
            reason=f"Cross-team request ({request.requester.team} -> {resource.owning_team})",
            required_approval_groups=[MANAGER_GROUP, OWNER_GROUP],
            metadata=peer_metadata,
        )

    if (
        tier == SensitivityTier.INTERNAL
        and resource.capability == "read"
        and not cross_team
    ):
        return _grant(
            request,
            resource,
            reason="Auto-Approved: Standard internal read access within team (Velocity-Benefit-01).",
            ttl_hours=336,
            metadata=peer_metadata,
        )

    if tier == SensitivityTier.INTERNAL and not cross_team:
        # Internal write within the owning team, already inside the duration limit above.
        return _grant(
            request,
            resource,
            reason=f"Auto-Approved: internal {resource.capability} within team, {requested_days}d within {max_days}d limit (Velocity-Benefit-01b).",
            ttl_hours=max(1, requested_days) * 24,
            metadata=peer_metadata,
        )

    if tier == SensitivityTier.PUBLIC:
        return _grant(
            request,
            resource,
            reason="Auto-Approved: Public low-sensitivity access (Velocity-Benefit-02).",
            ttl_hours=24,
            metadata=peer_metadata,
        )

    if tier == SensitivityTier.RESTRICTED:
        return _evaluate_level_2(request, resource, policy, peer_metadata=peer_metadata)

    if tier == SensitivityTier.CRITICAL:
        return _evaluate_level_3(request, resource, policy, peer_metadata=peer_metadata)

    return _escalate(
        request,
        resource,
        policy,
        reason=f"Unhandled sensitivity tier '{tier.value}'",
        metadata=peer_metadata,
    )


def _identity_revocation(
    grant: Grant, context: PolicyEvaluationContext
) -> RevocationAction | None:
    status = _hr_status(context.hr_system.get(grant.requester_id))
    if status and status != "ACTIVE":
        return RevocationAction(
            grant_id=grant.id,
            requester_id=grant.requester_id,
            resource_id=grant.resource_id,
            reason="User identity no longer active in HR heartbeat.",
            metadata={"hr_status": status, "reaper_trigger": "identity_purge"},
            decided_at=context.current_date,
        )
    return None


def _justification_revocation(
    grant: Grant, context: PolicyEvaluationContext
) -> RevocationAction | None:
    ticket_id = grant.metadata.get("ticket_id")
    incident_id = grant.metadata.get("incident_id")

    if ticket_id:
        status = _signal_status(context.external_signals.get("jira", {}), ticket_id)
        if status in {"DONE", "RESOLVED", "CLOSED"}:
            return RevocationAction(
                grant_id=grant.id,
                requester_id=grant.requester_id,
                resource_id=grant.resource_id,
                reason=f"Justification ticket {ticket_id} has been closed; work completed.",
                metadata={
                    "ticket_id": ticket_id,
                    "ticket_status": status,
                    "reaper_trigger": "justification_sunset",
                },
                decided_at=context.current_date,
            )

    if incident_id:
        status = _signal_status(context.external_signals.get("pagerduty", {}), incident_id)
        if status in {"DONE", "RESOLVED", "CLOSED"}:
            return RevocationAction(
                grant_id=grant.id,
                requester_id=grant.requester_id,
                resource_id=grant.resource_id,
                reason=f"Justification incident {incident_id} has been closed; work completed.",
                metadata={
                    "incident_id": incident_id,
                    "incident_status": status,
                    "reaper_trigger": "justification_sunset",
                },
                decided_at=context.current_date,
            )

    return None


def _finance_reaper_revocation(
    grant: Grant, resource: Resource, context: PolicyEvaluationContext
) -> RevocationAction | None:
    capability = (grant.capability or grant.metadata.get("capability") or resource.capability).lower()
    if (
        _resource_value(resource, "surface") == "FINANCE_PROD"
        and capability == "write"
        and _is_quiet_period(context)
        and grant.granted_at <= context.current_date
    ):
        return RevocationAction(
            grant_id=grant.id,
            requester_id=grant.requester_id,
            resource_id=grant.resource_id,
            reason="System entered Finance Quiet Period; Write access reclaimed.",
            metadata={
                "capability": capability,
                "reaper_trigger": "finance_quiet_period",
                "restriction": "READ_ONLY",
            },
            decided_at=context.current_date,
        )
    return None


def _geofence_reaper_revocation(
    grant: Grant, resource: Resource, context: PolicyEvaluationContext
) -> RevocationAction | None:
    center = resource.metadata.get("geofence_center")
    if not center:
        return None
    if _distance_meters(context.requester_location, center) > 500:
        return RevocationAction(
            grant_id=grant.id,
            requester_id=grant.requester_id,
            resource_id=grant.resource_id,
            reason="User moved out of physical authorized range for IoT control.",
            metadata={"reaper_trigger": "geofence_breach"},
            decided_at=context.current_date,
        )
    return None


def _hr_status(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.upper()
    if isinstance(value, dict):
        status = value.get("status")
        return status.upper() if isinstance(status, str) else status
    return None


def _signal_status(signals: dict, key: str) -> str | None:
    value = signals.get(key)
    if isinstance(value, str):
        return value.upper()
    if isinstance(value, dict):
        status = value.get("status")
        return status.upper() if isinstance(status, str) else status
    return None

def _global_hard_deny_reason(request: AccessRequest, now: datetime) -> str | None:
    requester = request.requester

    if not requester.is_active or not requester.is_active_employee:
        return "CRITICAL: Requester is marked as INACTIVE in HR systems."

    last_hr_sync = requester.last_hr_sync
    if last_hr_sync.tzinfo is None:
        last_hr_sync = last_hr_sync.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if now - last_hr_sync > HR_SYNC_MAX_AGE:
        return "CRITICAL: Requester HR heartbeat is stale (>24h since last sync)."

    if not _has_business_context(request):
        return "Auto-Denied: Missing business context; ticket_id or incident_id is required (JIT-Evidence-01)."

    return None


def _per_resource_hard_deny_reason(request: AccessRequest) -> str | None:
    requester = request.requester
    context = request.context

    if not context.device_compliant:
        return "Non-compliant device"

    if requester.risk_score > 70:
        return "Elevated user risk score"

    return None


def _effective_requested_duration_days(request: AccessRequest) -> int:
    if request.requester.type == "SEASONAL_CONTRACTOR":
        return min(request.requested_duration_days, 30)
    return request.requested_duration_days


def _agent_deny_reason(
    request: AccessRequest, active_grants: Iterable[Grant] | None
) -> str | None:
    if request.requester.identity_type != "agent":
        return None

    active_count = sum(
        1
        for grant in (active_grants or [])
        if grant.requester_id == request.requester.id and not grant.revoked
    )
    if active_count > 5:
        return (
            "Auto-Denied: AI agent already has more than 5 active grants "
            "(Runaway-Agent-01)."
        )

    if len(request.resource_ids) > MAX_BLAST_RADIUS:
        return (
            f"Auto-Denied: AI agent requested {len(request.resource_ids)} resources "
            "at once (Bot-Scraper-01)."
        )

    return None


def _has_business_context(request: AccessRequest) -> bool:
    return bool(_ticket_id(request) or _incident_id(request))


def _ticket_id(request: AccessRequest) -> str | None:
    return request.metadata.get("ticket_id") or request.context.active_jira_ticket


def _incident_id(request: AccessRequest) -> str | None:
    return request.metadata.get("incident_id") or request.context.active_pagerduty_incident


def _evaluation_context(
    context: PolicyEvaluationContext | dict | None,
    fallback_date: datetime,
) -> PolicyEvaluationContext:
    if isinstance(context, PolicyEvaluationContext):
        return context
    if isinstance(context, dict):
        return PolicyEvaluationContext.model_validate(context)
    return PolicyEvaluationContext(current_date=fallback_date)


def _blast_radius_reason(
    request: AccessRequest, active_grants: Iterable[Grant] | None
) -> str | None:
    if len(request.resource_ids) > MAX_BLAST_RADIUS:
        return (
            f"Blast radius exceeded: requesting {len(request.resource_ids)} resources "
            "at once; escalate to Engineering VP (CapitalOne-Risk-01)."
        )

    active_resource_ids = {
        grant.resource_id
        for grant in (active_grants or [])
        if grant.requester_id == request.requester.id and not grant.revoked
    }
    total_resources = len(active_resource_ids | set(request.resource_ids))
    if total_resources > MAX_ACTIVE_RESOURCES:
        return (
            f"Blast radius exceeded: requester would hold {total_resources} active "
            "resources; escalate to Engineering VP (CapitalOne-Risk-02)."
        )

    return None


def _circuit_breaker_decision(
    request: AccessRequest,
    request_history: Iterable[RequestHistoryEvent | dict] | None,
    now: datetime,
) -> PolicyDecision | None:
    if not request_history:
        return None

    denied_counts = [
        _denies_for_resource(request, resource_id, request_history, now)
        for resource_id in request.resource_ids
    ]
    max_denies = max(denied_counts, default=0)

    if max_denies >= 4:
        return PolicyDecision(
            request_id=request.id,
            resource_id="multiple" if len(request.resource_ids) > 1 else request.resource_ids[0],
            decision=DecisionType.ESCALATE,
            reason=(
                "Security Alert: repeated denied attempts triggered SOC circuit breaker "
                "(Anti-BruteForce-02)."
            ),
            required_approval_groups=[SOC_GROUP],
            metadata={"risk_score": "high", "policy_violation": "5x Rejection Rule"},
            audit_tags=["soc_alert", "circuit_breaker"],
        )

    if max_denies >= 3:
        return PolicyDecision(
            request_id=request.id,
            resource_id="multiple" if len(request.resource_ids) > 1 else request.resource_ids[0],
            decision=DecisionType.AUTO_DENY,
            reason=(
                "Circuit Breaker Active: too many failed attempts for the same resource "
                "inside 24h; hard locked for 24h (Anti-BruteForce-01)."
            ),
            metadata={"risk_score": "high", "policy_violation": "5x Rejection Rule"},
            audit_tags=["circuit_breaker"],
        )

    return None


def _denies_for_resource(
    request: AccessRequest,
    resource_id: str,
    request_history: Iterable[RequestHistoryEvent | dict],
    now: datetime,
) -> int:
    cutoff = now - timedelta(hours=24)
    count = 0
    for event in request_history:
        requester_id = _history_value(event, "requester_id")
        event_resource_id = _history_value(event, "resource_id")
        decision = _history_value(event, "decision")
        timestamp = _history_value(event, "timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if timestamp is None:
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        if (
            requester_id == request.requester.id
            and event_resource_id == resource_id
            and decision in {DecisionType.AUTO_DENY, DecisionType.AUTO_DENY.value, "deny"}
            and timestamp >= cutoff
        ):
            count += 1
    return count


def _history_value(event: RequestHistoryEvent | dict, key: str):
    if isinstance(event, dict):
        return event.get(key)
    return getattr(event, key)


def _effective_tier(resource: Resource) -> tuple[SensitivityTier, str | None]:
    if resource.capability in DESTRUCTIVE_CAPABILITIES:
        return (
            SensitivityTier.CRITICAL,
            (
                "DESTRUCTIVE ACTION DETECTED: "
                f"capability '{resource.capability}' upgrades access to critical tier (Ramesh-Rule-01)"
            ),
        )

    return resource.sensitivity, None


def _surface_decision(
    request: AccessRequest,
    resource: Resource,
    policy: PolicyRule,
    *,
    active_grants: Iterable[Grant] | None,
    peer_metadata: dict,
) -> PolicyDecision | None:
    if resource.type in {ResourceType.GITHUB_REPO, ResourceType.GITHUB_REPO_UPPER}:
        return _github_decision(request, resource, policy, peer_metadata)

    if resource.type in {ResourceType.POWERBI_DATASET, ResourceType.POWERBI_DATASET_UPPER}:
        return _powerbi_decision(request, resource, policy, peer_metadata)

    if resource.type in {
        ResourceType.SAP_BUSINESS_PARTNER,
        ResourceType.SAP_BILLING_DOCUMENT,
        ResourceType.SAP_SALES_ORDER,
        ResourceType.SAP_CUSTOMER_DIRECTORY,
        ResourceType.SAP_HR_PAYROLL,
    }:
        return _sap_decision(request, resource, policy, peer_metadata)

    return None


def _industry_shield_decision(
    request: AccessRequest,
    resource: Resource,
    policy: PolicyRule,
    context: PolicyEvaluationContext,
    *,
    active_grants: Iterable[Grant] | None,
    peer_metadata: dict,
) -> PolicyDecision | None:
    base_metadata = {
        **peer_metadata,
        "compliance_checked": _compliance_checks(resource),
        "context_snapshot": _context_snapshot(context),
    }

    finance_decision = _finance_shield_decision(
        request, resource, policy, context, base_metadata
    )
    if finance_decision is not None:
        return finance_decision

    retail_decision = _retail_shield_decision(
        request, resource, context, base_metadata
    )
    if retail_decision is not None:
        return retail_decision

    tech_decision = _tech_ops_shield_decision(
        request,
        resource,
        policy,
        context,
        active_grants=active_grants,
        metadata=base_metadata,
    )
    if tech_decision is not None:
        return tech_decision

    return None


def _finance_shield_decision(
    request: AccessRequest,
    resource: Resource,
    policy: PolicyRule,
    context: PolicyEvaluationContext,
    metadata: dict,
) -> PolicyDecision | None:
    if resource.type in {ResourceType.PAYMENT_RAIL, ResourceType.PAYMENT_RAIL_UPPER}:
        return PolicyDecision(
            request_id=request.id,
            resource_id=resource.id,
            decision=DecisionType.WITNESS_REQUIRED,
            reason="Witness Required: payment rail access requires two authorized humans for a valid session (PCI-DSS-3.2).",
            required_approval_groups=[WITNESS_GROUP, OWNER_GROUP],
            metadata={
                **metadata,
                "policy_violation": "PCI Witness Rule",
                "witness_required": True,
                "risk_score": "high",
            },
        )

    if (
        _resource_value(resource, "surface") == "FINANCE_PROD"
        and _is_quiet_period(context)
    ):
        return _escalate(
            request,
            resource,
            policy,
            reason="SOX Compliance: Earnings Quiet Period; write access downgraded to read-only.",
            effective_tier=SensitivityTier.CRITICAL,
            required_approval_groups=[CFO_GROUP],
            metadata={
                **metadata,
                "policy_violation": "SOX Quiet Period",
                "downgraded_capability": "read",
                "restriction": "READ_ONLY",
                "risk_score": "high",
            },
        )

    return None


def _retail_shield_decision(
    request: AccessRequest,
    resource: Resource,
    context: PolicyEvaluationContext,
    metadata: dict,
) -> PolicyDecision | None:
    if (
        resource.type in {ResourceType.WMS_IOT, ResourceType.WMS_IOT_UPPER}
        or _resource_value(resource, "category") == "WMS_IOT"
    ):
        center = resource.metadata.get("geofence_center")
        if center and _distance_meters(context.requester_location, center) > 500:
            return _deny(
                request,
                resource.id,
                "Physical presence required for IoT control.",
                metadata={
                    **metadata,
                    "policy_violation": "Warehouse Geofence",
                    "risk_score": "high",
                },
            )

    if request.requester.type == "SEASONAL_CONTRACTOR":
        metadata.update(
            {
                "max_duration_days": 30,
                "renew_access_disabled": True,
                "policy_violation": "Seasonal Contractor Sunset",
            }
        )

    return None


def _tech_ops_shield_decision(
    request: AccessRequest,
    resource: Resource,
    policy: PolicyRule,
    context: PolicyEvaluationContext,
    *,
    active_grants: Iterable[Grant] | None,
    metadata: dict,
) -> PolicyDecision | None:
    if resource.type in {
        ResourceType.IMPERSONATION_TOOL,
        ResourceType.IMPERSONATION_TOOL_UPPER,
    }:
        ticket_id = _ticket_id(request)
        zendesk = context.external_signals.get("zendesk", {})
        ticket = zendesk.get(ticket_id, {}) if ticket_id else {}
        ticket_email = ticket.get("requester_email")
        target_email = request.metadata.get("target_user_email") or resource.metadata.get("target_user_email")
        if not ticket_id or not ticket_email or ticket_email != target_email:
            return _deny(
                request,
                resource.id,
                "Trust: Ticket requester does not match target user.",
                metadata={
                    **metadata,
                    "policy_violation": "Support Impersonation Mismatch",
                    "risk_score": "high",
                    "ticket_id": ticket_id,
                    "ticket_requester_email": ticket_email,
                    "target_user_email": target_email,
                },
            )

    if _resource_value(resource, "surface") == "BUILD_PIPELINE" or resource.type in {
        ResourceType.BUILD_PIPELINE,
        ResourceType.BUILD_PIPELINE_UPPER,
    }:
        scan = _recent_critical_scan(request, context)
        if scan is not None:
            return _escalate(
                request,
                resource,
                policy,
                reason="CI/CD Safety Sync: critical vulnerability pushed in the last 24h; Security Architect review required.",
                effective_tier=SensitivityTier.CRITICAL,
                required_approval_groups=[SECURITY_ARCHITECT_GROUP],
                metadata={
                    **metadata,
                    "policy_violation": "Critical Vulnerability Push",
                    "risk_score": "high",
                    "scan_report": scan,
                },
            )

    if resource.type in {ResourceType.VAULT_SECRET, ResourceType.VAULT_SECRET_UPPER}:
        secret_count = _recent_secret_count(request, active_grants, context)
        if secret_count >= 3:
            return _deny(
                request,
                resource.id,
                "Anomaly: Potential secret harvesting detected.",
                metadata={
                    **metadata,
                    "policy_violation": "Secret Harvesting Threshold",
                    "risk_score": "high",
                    "anomaly_alarm": True,
                    "recent_secret_count": secret_count + 1,
                },
            )

    return None


def _resource_value(resource: Resource, key: str) -> str | None:
    value = getattr(resource, key, None) or resource.metadata.get(key)
    return value.upper() if isinstance(value, str) else value


def _compliance_checks(resource: Resource) -> list[str]:
    checks = []
    if _resource_value(resource, "surface") == "FINANCE_PROD":
        checks.append("SOX-404")
    if resource.type in {ResourceType.PAYMENT_RAIL, ResourceType.PAYMENT_RAIL_UPPER}:
        checks.append("PCI-DSS-3.2")
    if resource.metadata.get("has_pii") or resource.type in {
        ResourceType.POWERBI_DATASET,
        ResourceType.POWERBI_DATASET_UPPER,
        ResourceType.IMPERSONATION_TOOL,
        ResourceType.IMPERSONATION_TOOL_UPPER,
    }:
        checks.append("GDPR-Art-32")
    return checks


def _context_snapshot(context: PolicyEvaluationContext) -> dict:
    scans = context.external_signals.get("security_scans", {})
    return {
        "location": context.requester_location.get("label"),
        "quiet_period": _is_quiet_period(context),
        "snyk_score": scans.get("snyk_score") or scans.get("status"),
    }


def _is_quiet_period(context: PolicyEvaluationContext) -> bool:
    periods = context.company_calendar.get("quiet_period", [])
    if isinstance(periods, dict):
        periods = [periods]
    current = context.current_date
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    for period in periods:
        start = _parse_dt(period.get("start"))
        end = _parse_dt(period.get("end"))
        if start and end and start <= current <= end:
            return True
    return False


def _parse_dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _distance_meters(a: dict, b: dict) -> float:
    if not a or not b:
        return float("inf")
    lat1, lon1 = radians(float(a["lat"])), radians(float(a["lon"]))
    lat2, lon2 = radians(float(b["lat"])), radians(float(b["lon"]))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * 6371000 * asin(sqrt(h))


def _recent_critical_scan(
    request: AccessRequest, context: PolicyEvaluationContext
) -> dict | None:
    scans = context.external_signals.get("security_scans", {})
    entries = scans.get("findings", [])
    cutoff = context.current_date - timedelta(hours=24)
    for entry in entries:
        timestamp = _parse_dt(entry.get("timestamp"))
        if (
            entry.get("requester_id") == request.requester.id
            and entry.get("severity") == "Critical Vulnerability"
            and timestamp
            and timestamp >= cutoff
        ):
            return entry
    return None


def _recent_secret_count(
    request: AccessRequest,
    active_grants: Iterable[Grant] | None,
    context: PolicyEvaluationContext,
) -> int:
    current = context.current_date
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = current - timedelta(minutes=60)
    return len(
        {
            grant.resource_id
            for grant in (active_grants or [])
            if grant.requester_id == request.requester.id
            and not grant.revoked
            and grant.granted_at >= cutoff
            and grant.resource_id.startswith("secret-")
        }
    )


def _github_decision(
    request: AccessRequest,
    resource: Resource,
    policy: PolicyRule,
    peer_metadata: dict,
) -> PolicyDecision | None:
    capability = resource.capability.lower()
    target = (resource.target or "").lower()

    if capability == "admin" or target == "main_branch":
        return _deny(
            request,
            resource.id,
            "Auto-Denied: GitHub admin or main_branch access is manual-only (GitHub-Lockdown-01).",
            metadata={**peer_metadata, "policy_violation": "GitHub Capability Lockdown"},
        )

    if request.requester.tenure_days < 90 and resource.metadata.get("is_critical"):
        return _escalate(
            request,
            resource,
            policy,
            reason=(
                "Escalated: new-hire access to critical GitHub repository requires "
                "Security Lead review (GitHub-Tenure-01)."
            ),
            effective_tier=SensitivityTier.CRITICAL,
            required_approval_groups=[SECURITY_LEAD_GROUP, OWNER_GROUP],
            metadata={
                **peer_metadata,
                "risk_score": "high",
                "policy_violation": "GitHub Tenure Guard",
            },
        )

    return None


def _powerbi_decision(
    request: AccessRequest,
    resource: Resource,
    policy: PolicyRule,
    peer_metadata: dict,
) -> PolicyDecision | None:
    capability = resource.capability.lower()
    metadata = dict(peer_metadata)
    if resource.metadata.get("has_pii"):
        metadata["restriction"] = "DISABLE_EXPORT"

    if capability == "view":
        return _grant(
            request,
            resource,
            reason="Auto-Approved: PowerBI view-only access (BI-Velocity-01).",
            ttl_hours=24,
            metadata=metadata,
        )

    if capability in {"export", "power_query"}:
        return _escalate(
            request,
            resource,
            policy,
            reason=(
                "Escalated: PowerBI export or Power Query access requires Data Steward "
                "review (BI-ActionSeparation-01)."
            ),
            effective_tier=SensitivityTier.RESTRICTED,
            required_approval_groups=[DATA_STEWARD_GROUP],
            metadata={
                **metadata,
                "risk_score": "high" if capability == "export" else "medium",
                "policy_violation": "PowerBI Action Separation",
            },
        )

    return None


def _sap_decision(
    request: AccessRequest,
    resource: Resource,
    policy: PolicyRule,
    peer_metadata: dict,
) -> PolicyDecision | None:
    if resource.type in {ResourceType.SAP_CUSTOMER_DIRECTORY, ResourceType.SAP_HR_PAYROLL}:
        return _deny(
            request,
            resource.id,
            "Auto-Denied: customer-directory export is not grantable; "
            "scope a single Business Partner (Conduct-SAP-01).",
            metadata={**peer_metadata, "policy_violation": "Conduct-SAP-01"},
        )

    return None


def _correlation_risk_decision(
    request: AccessRequest,
    resource: Resource,
    resources: dict[str, Resource] | None,
    active_grants: Iterable[Grant] | None,
    peer_metadata: dict,
    policy: PolicyRule,
) -> PolicyDecision | None:
    risky_with = set(resource.metadata.get("correlation_risk_with", []))
    if not risky_with:
        return None

    held_resource_ids = {
        grant.resource_id
        for grant in (active_grants or [])
        if grant.requester_id == request.requester.id and not grant.revoked
    }
    if held_resource_ids.isdisjoint(risky_with):
        return None

    return _escalate(
        request,
        resource,
        policy,
        reason="Potential Data Correlation Risk.",
        effective_tier=SensitivityTier.RESTRICTED,
        required_approval_groups=[DATA_STEWARD_GROUP, SEC_OPS_GROUP],
        metadata={
            **peer_metadata,
            "risk_score": "high",
            "policy_violation": "Separation of Duties",
            "correlated_resources": sorted(held_resource_ids & risky_with),
        },
    )


def _authentication_decision(
    request: AccessRequest, resource: Resource
) -> PolicyDecision | None:
    if request.requester.auth_type not in PHISHING_RESISTANT_AUTH:
        return PolicyDecision(
            request_id=request.id,
            resource_id=resource.id,
            decision=DecisionType.STEP_UP_AUTH_REQUIRED,
            reason="Authenticate with a phishing-resistant hardware token or passkey",
        )

    if request.context.location_anomaly and resource.sensitivity == SensitivityTier.CRITICAL:
        return PolicyDecision(
            request_id=request.id,
            resource_id=resource.id,
            decision=DecisionType.ESCALATE,
            reason="Anomaly detected on critical asset",
        )

    return None


def _evaluate_level_2(
    request: AccessRequest,
    resource: Resource,
    policy: PolicyRule,
    *,
    peer_metadata: dict,
) -> PolicyDecision:
    return _escalate(
        request,
        resource,
        policy,
        reason="Escalated: Restricted or cross-team access requires manager and owner verification (Sentinel-Restricted-01).",
        required_approval_groups=[MANAGER_GROUP, OWNER_GROUP],
        metadata=peer_metadata,
    )


def _evaluate_level_3(
    request: AccessRequest,
    resource: Resource,
    policy: PolicyRule,
    *,
    peer_metadata: dict,
) -> PolicyDecision:
    return _escalate(
        request,
        resource,
        policy,
        reason="Escalated: Critical access requires Sec-Ops and owner verification (Sentinel-Critical-01).",
        required_approval_groups=[SEC_OPS_GROUP, OWNER_GROUP],
        metadata=peer_metadata,
    )


def _grant(
    request: AccessRequest,
    resource: Resource,
    *,
    reason: str,
    ttl_hours: int,
    audit_tags: list[str] | None = None,
    metadata: dict | None = None,
) -> PolicyDecision:
    if request.requester.identity_type == "agent":
        ttl_hours = min(ttl_hours, 1)
        audit_tags = [*(audit_tags or []), "agent_session_bound_ttl"]
    if request.requester.type == "SEASONAL_CONTRACTOR":
        ttl_hours = min(ttl_hours, 30 * 24)
        metadata = {
            **(metadata or {}),
            "max_duration_days": 30,
            "renew_access_disabled": True,
        }

    return PolicyDecision(
        request_id=request.id,
        resource_id=resource.id,
        decision=DecisionType.AUTO_GRANT,
        reason=reason,
        ttl_hours=ttl_hours,
        audit_tags=audit_tags or [],
        metadata=metadata or {},
    )


def _deny(
    request: AccessRequest,
    resource_id: str,
    reason: str,
    *,
    metadata: dict | None = None,
) -> PolicyDecision:
    return PolicyDecision(
        request_id=request.id,
        resource_id=resource_id,
        decision=DecisionType.AUTO_DENY,
        reason=reason,
        metadata=metadata or {},
    )


def _escalate(
    request: AccessRequest,
    resource: Resource,
    policy: PolicyRule,
    *,
    reason: str,
    effective_tier: SensitivityTier | None = None,
    required_approval_groups: list[str] | None = None,
    metadata: dict | None = None,
) -> PolicyDecision:
    tier = effective_tier or resource.sensitivity
    n = policy.required_approvals.get(tier, 1)
    # Placeholder approver resolution — usecase-demo / backend-api should supply real
    # team-owner -> approver-id mappings; for now we surface the count needed and let
    # backend-api resolve required_approver_ids from resource.owning_team (+ requester's
    # manager, if cross-team policy wants both sides represented).
    return PolicyDecision(
        request_id=request.id,
        resource_id=resource.id,
        decision=DecisionType.ESCALATE,
        reason=f"{reason} — requires {n} approval(s)",
        required_approver_ids=[],  # TODO(backend-api/usecase-demo): resolve real approver ids
        required_approval_groups=required_approval_groups or [],
        metadata=metadata or {},
    )


def _peer_metadata(
    request: AccessRequest,
    resource: Resource,
    active_grants: Iterable[Grant] | None,
    team_size_by_team: dict[str, int] | None,
) -> dict:
    team_size = (team_size_by_team or {}).get(request.requester.team)
    team_holders = {
        grant.requester_id
        for grant in (active_grants or [])
        if grant.resource_id == resource.id and not grant.revoked
    }

    metadata = {
        "peer_signal": "Peer comparison unavailable",
        "peer_access_count": len(team_holders),
        "peer_team_size": team_size,
    }
    if not team_size:
        return metadata

    ratio = len(team_holders) / team_size
    metadata["peer_access_ratio"] = ratio
    metadata["peer_signal"] = (
        f"{len(team_holders)} of {team_size} team members currently hold access "
        f"to {resource.name} ({ratio:.0%})."
    )
    if ratio < 0.10:
        metadata["peer_warning"] = "Warning: Outlier Request"

    return metadata
