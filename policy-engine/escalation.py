"""
Multi-stakeholder escalation resolution: turns an ESCALATE PolicyDecision into an
EscalationCase, and resolves votes into a final approved/denied status (N-of-M).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from shared.schemas import ApprovalVote, EscalationCase, PolicyDecision  # noqa: E402


def open_case(
    decision: PolicyDecision,
    case_id: str,
    approver_ids: list[str],
    requester_id: str,
    requested_duration_days: int,
) -> EscalationCase:
    return EscalationCase(
        id=case_id,
        request_id=decision.request_id,
        resource_id=decision.resource_id,
        required_approver_ids=approver_ids,
        requester_id=requester_id,
        requested_duration_days=requested_duration_days,
        status="pending",
    )


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
