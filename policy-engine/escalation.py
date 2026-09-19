"""
Multi-stakeholder escalation resolution: turns an ESCALATE PolicyDecision into an
EscalationCase, and resolves votes into a final approved/denied status (N-of-M).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from shared.schemas import (  # noqa: E402
    AccessRequest,
    ApprovalVote,
    EscalationCase,
    PolicyDecision,
    Resource,
)


INCIDENT_SLA_MINUTES = 30
STANDARD_SLA_HOURS = 4


def open_case(
    decision: PolicyDecision,
    case_id: str,
    approver_ids: list[str],
    requester_id: str,
    requested_duration_days: int,
    *,
    request: AccessRequest | None = None,
    resource: Resource | None = None,
    now: datetime | None = None,
) -> EscalationCase:
    opened_at = now or decision.evaluated_at
    incident_backed = _has_incident_context(request, decision)

    return EscalationCase(
        id=case_id,
        request_id=decision.request_id,
        resource_id=decision.resource_id,
        required_approver_ids=_dedupe(approver_ids),
        requester_id=requester_id,
        requested_duration_days=requested_duration_days,
        escalation_reason=decision.reason,
        human_summary=synthesize_summary(request, resource, decision) if request and resource else decision.reason,
        routing_rationale=routing_rationale(request, resource, approver_ids) if request and resource else None,
        peer_percentile=decision.metadata.get("peer_signal"),
        risk_score=decision.metadata.get("risk_score") or _risk_score(decision, resource),
        policy_violation=decision.metadata.get("policy_violation") or decision.reason,
        suggested_downgrade=suggested_downgrade(request, resource, decision) if request and resource else None,
        metadata=decision.metadata,
        opened_at=opened_at,
        sla_due_at=sla_deadline(opened_at, incident_backed=incident_backed),
        timeout_action="default_escalate" if incident_backed else "auto_deny",
        status="pending",
    )


def synthesize_summary(
    request: AccessRequest, resource: Resource, decision: PolicyDecision
) -> str:
    """Build the concise approval-card summary from typed request context."""
    context = request.context
    evidence = []

    if context.active_pagerduty_incident:
        evidence.append(f"PagerDuty incident {context.active_pagerduty_incident}")
    if context.active_jira_ticket:
        evidence.append(f"Jira ticket {context.active_jira_ticket}")
    if context.location:
        evidence.append(f"location: {context.location}")
    if context.justification_provided:
        evidence.append(f"justification: {context.justification_provided}")

    evidence_text = "; ".join(evidence) if evidence else "no ticket, incident, or location detail supplied"
    return (
        f"{request.requester.name} ({request.requester.role}, risk {request.requester.risk_score}) "
        f"requests {request.requested_duration_days}d access to {resource.name} "
        f"({resource.sensitivity.value}, owner {resource.owning_team}). "
        f"Escalation reason: {decision.reason}. Context: {evidence_text}."
    )


def routing_rationale(
    request: AccessRequest, resource: Resource, approver_ids: list[str]
) -> str:
    route_targets = []
    if resource.owner_group:
        route_targets.append(f"resource owner group {resource.owner_group}")
    else:
        route_targets.append(f"resource owning team {resource.owning_team}")

    if request.requester.manager_email:
        route_targets.append(f"requester manager {request.requester.manager_email}")
    elif request.requester.manager_id:
        route_targets.append(f"requester manager {request.requester.manager_id}")

    return f"Routed to {', '.join(route_targets)}; required approvers: {', '.join(_dedupe(approver_ids))}"


def sla_deadline(opened_at: datetime, *, incident_backed: bool) -> datetime:
    if incident_backed:
        return opened_at + timedelta(minutes=INCIDENT_SLA_MINUTES)
    return opened_at + timedelta(hours=STANDARD_SLA_HOURS)


def apply_timeout(case: EscalationCase, now: datetime) -> EscalationCase:
    """Close a pending case when its SLA expires."""
    if case.status != "pending" or case.sla_due_at is None or now < case.sla_due_at:
        return case

    if case.timeout_action == "auto_deny":
        return case.model_copy(update={"status": "denied"})

    return case


def apply_vote(case: EscalationCase, vote: ApprovalVote) -> EscalationCase:
    """Return an updated copy of `case` with `vote` applied and status recomputed.

    Votes from anyone not in required_approver_ids are ignored — otherwise any id could
    deny (any-veto) or be counted toward approval.
    """
    if case.status != "pending" or vote.approver_id not in case.required_approver_ids:
        return case

    votes = [v for v in case.votes if v.approver_id != vote.approver_id] + [vote]
    case = case.model_copy(update={"votes": votes})

    if any(not v.approved for v in votes):
        return case.model_copy(update={"status": "denied"})

    approved_ids = {v.approver_id for v in votes if v.approved}
    if set(case.required_approver_ids).issubset(approved_ids):
        return case.model_copy(update={"status": "approved"})

    return case


def suggested_downgrade(
    request: AccessRequest, resource: Resource, decision: PolicyDecision
) -> str | None:
    capability = resource.capability.lower()
    if capability in {"admin", "delete", "drop", "terminate", "iam_change"} or request.requested_duration_days > 1:
        return "Grant READ for 4 hours"
    if capability in {"export", "power_query"}:
        return "Grant VIEW with DISABLE_EXPORT for 4 hours"
    return None


def _risk_score(decision: PolicyDecision, resource: Resource | None) -> str:
    reason = decision.reason.lower()
    capability = resource.capability.lower() if resource else ""
    if capability in {"admin", "delete", "drop", "terminate", "iam_change", "export", "power_query"}:
        return "high"
    if "critical" in reason or "blast" in reason or "circuit breaker" in reason:
        return "high"
    if "cross-team" in reason or "restricted" in reason:
        return "medium"
    return "low"


def _has_incident_context(
    request: AccessRequest | None, decision: PolicyDecision
) -> bool:
    if request and request.context.active_pagerduty_incident:
        return True
    reason = decision.reason.lower()
    return "incident" in reason or "pagerduty" in reason


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
