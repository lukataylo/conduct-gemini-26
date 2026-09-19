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
    DecisionType,
    PolicyDecision,
    PolicyRule,
    Resource,
    SensitivityTier,
)

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

    return PolicyDecision(
        request_id=request.id,
        resource_id=resource.id,
        decision=DecisionType.AUTO_GRANT,
        reason=(
            f"{tier.value} tier, {request.requested_duration_days}d within {max_days}d limit, "
            "same-team requester"
        ),
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
