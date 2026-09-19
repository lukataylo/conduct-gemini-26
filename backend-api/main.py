"""
FastAPI hub. Owns persistence (in-memory for the hackathon; swap for real DB if there's
time) and wires policy-engine + agent-runtime + usecase-demo data together behind a
small REST API that generative-ui and the demo script call.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from policy_engine_paths import escalation, policy_engine, usecase_demo  # noqa: E402
from shared.schemas import (  # noqa: E402
    AccessRequest,
    ApprovalVote,
    AuditEvent,
    AuditEventType,
    DecisionType,
    EscalationCase,
    Grant,
    UIComponentSpec,
    UISpec,
)

app = FastAPI(title="Access Scope Agent — backend-api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before anything resembling production
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- in-memory store (swap for real persistence if there's time) ----------------------
REQUESTS: dict[str, AccessRequest] = {}
GRANTS: dict[str, Grant] = {}
ESCALATIONS: dict[str, EscalationCase] = {}
AUDIT_LOG: list[AuditEvent] = []


def _audit(event_type: AuditEventType, actor: str, detail: str, **kw) -> AuditEvent:
    event = AuditEvent(id=str(uuid.uuid4()), type=event_type, actor=actor, detail=detail, **kw)
    AUDIT_LOG.append(event)
    return event


@app.post("/requests")
def submit_request(request: AccessRequest) -> dict:
    """Accepts an already-structured AccessRequest (agent-runtime parses NL upstream),
    evaluates it against policy-engine, and issues grants / opens escalations."""
    REQUESTS[request.id] = request
    _audit(AuditEventType.REQUEST_RECEIVED, actor=request.requester.id, detail=request.task_description, request_id=request.id)

    resources = usecase_demo.RESOURCES
    decisions = policy_engine.evaluate_request(request, resources)

    results = []
    for decision in decisions:
        _audit(
            AuditEventType.POLICY_EVALUATED,
            actor="policy-engine",
            detail=decision.reason,
            request_id=request.id,
            payload={"resource_id": decision.resource_id, "decision": decision.decision.value},
        )

        if decision.decision == DecisionType.AUTO_GRANT:
            grant = _issue_grant(request, decision.resource_id)
            results.append({"resource_id": decision.resource_id, "status": "granted", "grant_id": grant.id})

        elif decision.decision == DecisionType.ESCALATE:
            approvers = usecase_demo.APPROVERS.get(decision.resource_id, [])
            case = EscalationCase(
                id=str(uuid.uuid4()),
                request_id=request.id,
                resource_id=decision.resource_id,
                required_approver_ids=approvers,
            )
            ESCALATIONS[case.id] = case
            _audit(AuditEventType.ESCALATED, actor="policy-engine", detail=decision.reason, request_id=request.id, escalation_id=case.id)
            results.append({"resource_id": decision.resource_id, "status": "escalated", "escalation_id": case.id})

        else:
            results.append({"resource_id": decision.resource_id, "status": "denied", "reason": decision.reason})

    return {"request_id": request.id, "results": results}


@app.get("/escalations")
def list_escalations(status: str | None = None) -> list[EscalationCase]:
    cases = list(ESCALATIONS.values())
    if status:
        cases = [c for c in cases if c.status == status]
    return cases


@app.post("/escalations/{escalation_id}/vote")
def vote(escalation_id: str, vote: ApprovalVote) -> EscalationCase:
    case = ESCALATIONS.get(escalation_id)
    if case is None:
        raise HTTPException(404, "escalation not found")

    case = escalation.apply_vote(case, vote)
    ESCALATIONS[escalation_id] = case
    _audit(
        AuditEventType.APPROVAL_VOTE_CAST,
        actor=vote.approver_id,
        detail=f"{'approved' if vote.approved else 'denied'}",
        escalation_id=escalation_id,
        request_id=case.request_id,
    )

    if case.status == "approved":
        request = REQUESTS[case.request_id]
        _issue_grant(request, case.resource_id)

    return case


def _issue_grant(request: AccessRequest, resource_id: str, ttl_days: int | None = None) -> Grant:
    ttl = ttl_days or request.requested_duration_days
    grant = Grant(
        id=str(uuid.uuid4()),
        request_id=request.id,
        resource_id=resource_id,
        requester_id=request.requester.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=ttl),
    )
    GRANTS[grant.id] = grant
    _audit(AuditEventType.GRANT_ISSUED, actor="policy-engine", detail=f"granted {resource_id}", request_id=request.id, grant_id=grant.id)
    # TODO(contributor 2/5): call agent-runtime's execute_grant here (or enqueue it) so
    # the computer-use step actually performs the action against the mock console.
    return grant


@app.post("/grants/{grant_id}/revoke")
def revoke_grant(grant_id: str, reason: str = "expired") -> Grant:
    grant = GRANTS.get(grant_id)
    if grant is None:
        raise HTTPException(404, "grant not found")
    grant = grant.model_copy(update={"revoked": True, "revoked_at": datetime.now(timezone.utc), "revoked_reason": reason})
    GRANTS[grant_id] = grant
    _audit(AuditEventType.GRANT_REVOKED, actor="policy-engine", detail=reason, grant_id=grant_id, request_id=grant.request_id)
    return grant


@app.get("/audit")
def audit_trail(request_id: str | None = None) -> list[AuditEvent]:
    events = AUDIT_LOG
    if request_id:
        events = [e for e in events if e.request_id == request_id]
    return events


@app.get("/ui-spec/{requester_id}")
def ui_spec(requester_id: str) -> UISpec:
    """Builds the current UISpec for a requester from their active grants.

    TODO(contributor 1/2): replace this static mapping with a real Gemini call that
    takes {requester, active_grants, pending_escalations} and emits panel specs —
    this function is the seam generative-ui and agent-runtime both need to agree on.
    """
    active_grants = [g for g in GRANTS.values() if g.requester_id == requester_id and not g.revoked]

    pending = []
    for case in ESCALATIONS.values():
        if case.status != "pending":
            continue
        request = REQUESTS.get(case.request_id)
        if request is not None and request.requester.id == requester_id:
            pending.append(case)

    panels = [
        UIComponentSpec(component="GrantCard", props={"grant_id": g.id, "resource_id": g.resource_id, "expires_at": g.expires_at.isoformat()})
        for g in active_grants
    ] + [
        UIComponentSpec(component="PendingApprovalCard", props={"escalation_id": c.id, "resource_id": c.resource_id})
        for c in pending
    ]

    return UISpec(requester_id=requester_id, panels=panels)
