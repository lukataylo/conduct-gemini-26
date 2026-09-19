"""
Deterministic policy engine.

This is the security-critical path: no LLM in here. Gemini/Claude parse requests and
explain decisions elsewhere (agent-runtime); this module only ever sees typed input and
returns typed, deterministic output so every decision is reproducible and auditable.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from shared.schemas import (  # noqa: E402
    AccessRequest,
    AuthType,
    DecisionType,
    PolicyDecision,
    PolicyRule,
    Resource,
    SensitivityTier,
)

PHISHING_RESISTANT_AUTH = {
    AuthType.FIDO2_MFA,
    AuthType.PASSKEY,
    AuthType.HARDWARE_TOKEN,
}

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
) -> list[PolicyDecision]:
    """Evaluate one AccessRequest against every resource it names.

    Returns one PolicyDecision per resource_id — a single request can be granted on
    some resources and escalated on others (see README golden path: bucket auto-grants,
    dataset escalates, from the same request).
    """
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

        decisions.append(_evaluate_single(request, resource, policy))

    return decisions


def _evaluate_single(
    request: AccessRequest, resource: Resource, policy: PolicyRule
) -> PolicyDecision:
    hard_deny_reason = _hard_deny_reason(request)
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

    tier = resource.sensitivity
    cross_team = resource.owning_team != request.requester.team

    if tier in policy.always_escalate_tiers:
        return _escalate(request, resource, policy, reason=f"{tier.value} tier always escalates")

    max_days = policy.max_auto_grant_duration_days.get(tier, 0)
    if request.requested_duration_days > max_days:
        return _escalate(
            request,
            resource,
            policy,
            reason=(
                f"Requested {request.requested_duration_days}d exceeds auto-grant limit "
                f"of {max_days}d for {tier.value} tier"
            ),
        )

    if cross_team and policy.cross_team_requires_all_owners:
        return _escalate(
            request,
            resource,
            policy,
            reason=f"Cross-team request ({request.requester.team} -> {resource.owning_team})",
        )

    if tier in {SensitivityTier.PUBLIC, SensitivityTier.INTERNAL}:
        return _grant(
            request,
            resource,
            reason="Level 1 low-sensitivity asset auto-approved",
            ttl_hours=24,
        )

    if tier == SensitivityTier.RESTRICTED:
        return _evaluate_level_2(request, resource)

    if tier == SensitivityTier.CRITICAL:
        return _evaluate_level_3(request, resource, policy)

    return _escalate(request, resource, policy, reason=f"Unhandled sensitivity tier '{tier.value}'")


def _hard_deny_reason(request: AccessRequest) -> str | None:
    requester = request.requester
    context = request.context

    if not requester.is_active_employee:
        return "Inactive Identity"

    if not context.device_compliant:
        return "Non-compliant device"

    if requester.risk_score > 70:
        return "Elevated user risk score"

    return None


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


def _evaluate_level_2(request: AccessRequest, resource: Resource) -> PolicyDecision:
    context = request.context
    if context.active_jira_ticket or context.active_pagerduty_incident:
        return _grant(
            request,
            resource,
            reason="Level 2 medium-sensitivity asset with active ticket or incident",
            ttl_hours=8,
        )

    return _grant(
        request,
        resource,
        reason="Level 2 medium-sensitivity asset without ticket; mandatory audit tag applied",
        ttl_hours=2,
        audit_tags=["missing_ticket_context"],
    )


def _evaluate_level_3(
    request: AccessRequest, resource: Resource, policy: PolicyRule
) -> PolicyDecision:
    context = request.context
    risk_score = request.requester.risk_score

    if context.active_pagerduty_incident:
        return _grant(
            request,
            resource,
            reason="Level 3 critical asset auto-approved under incident emergency override",
            ttl_hours=1,
            audit_tags=["incident_emergency_override"],
        )

    if context.active_jira_ticket and risk_score < 30:
        return _grant(
            request,
            resource,
            reason="Level 3 critical asset with active Jira ticket and low requester risk",
            ttl_hours=4,
        )

    return _escalate(
        request,
        resource,
        policy,
        reason=(
            "High-value target lacks sufficient automated context or carries moderate risk"
        ),
    )


def _grant(
    request: AccessRequest,
    resource: Resource,
    *,
    reason: str,
    ttl_hours: int,
    audit_tags: list[str] | None = None,
) -> PolicyDecision:
    return PolicyDecision(
        request_id=request.id,
        resource_id=resource.id,
        decision=DecisionType.AUTO_GRANT,
        reason=reason,
        ttl_hours=ttl_hours,
        audit_tags=audit_tags or [],
    )


def _deny(request: AccessRequest, resource_id: str, reason: str) -> PolicyDecision:
    return PolicyDecision(
        request_id=request.id,
        resource_id=resource_id,
        decision=DecisionType.AUTO_DENY,
        reason=reason,
    )


def _escalate(
    request: AccessRequest, resource: Resource, policy: PolicyRule, *, reason: str
) -> PolicyDecision:
    n = policy.required_approvals.get(resource.sensitivity, 1)
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
    )
