"""
FastAPI hub. Owns persistence (in-memory for the hackathon) and wires policy-engine +
agent-runtime + usecase-demo data together behind a small REST API that generative-ui
and the demo script call.

Trust boundaries (see docs/ui-surfaces.html, "Hardening before the demo"):
- request ids and audit ids/hashes/timestamps are server-assigned, never client-supplied
- the requester is looked up server-side by id; posted team/manager fields are ignored
- an escalation snapshots requester + duration at open time and grants from the snapshot
- every reader of grants filters on expiry, not just `revoked`
"""
from __future__ import annotations

import hashlib
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
    Requester,
    UIComponentSpec,
    UISpec,
)

app = FastAPI(title="Aperture — backend-api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO(track 5): restrict to the deployed UI origin before Railway
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- in-memory store -------------------------------------------------------------------
REQUESTS: dict[str, AccessRequest] = {}
GRANTS: dict[str, Grant] = {}
ESCALATIONS: dict[str, EscalationCase] = {}
AUDIT_LOG: list[AuditEvent] = []

KNOWN_REQUESTERS: dict[str, Requester] = {
    r.id: r for r in (usecase_demo.REQUESTER, usecase_demo.MANAGER, usecase_demo.FINANCE_OWNER)
}


def now() -> datetime:
    # TODO(track 5): route through a demo clock with POST /clock/advance
    return datetime.now(timezone.utc)


def _hash(event: AuditEvent) -> str:
    return hashlib.sha256(event.model_dump_json().encode()).hexdigest()


def _audit(event_type: AuditEventType, actor: str, detail: str, **kw) -> AuditEvent:
    prev_hash = _hash(AUDIT_LOG[-1]) if AUDIT_LOG else None
    event = AuditEvent(
        id=str(uuid.uuid4()),
        type=event_type,
        actor=actor,
        detail=detail,
        prev_hash=prev_hash,
        timestamp=now(),
        **kw,
    )
    AUDIT_LOG.append(event)
    return event


@app.post("/requests")
def submit_request(request: AccessRequest) -> dict:
    """Accepts a structured AccessRequest (agent-runtime parses NL upstream), evaluates
    it against policy-engine, and issues grants / opens escalations."""
    requester = KNOWN_REQUESTERS.get(request.requester.id)
    if requester is None:
        raise HTTPException(400, f"unknown requester '{request.requester.id}'")

    request = request.model_copy(update={"id": str(uuid.uuid4()), "requester": requester})
    REQUESTS[request.id] = request
    _audit(
        AuditEventType.REQUEST_RECEIVED,
        actor=requester.id,
        detail=f"{len(request.resource_ids)} resource(s) for {request.requested_duration_days}d",
        request_id=request.id,
        payload={"task_description": request.task_description},  # requester's claim, unverified
    )

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
            grant = _issue_grant(request.id, requester.id, decision.resource_id, request.requested_duration_days)
            results.append({"resource_id": decision.resource_id, "status": "granted", "grant_id": grant.id})

        elif decision.decision == DecisionType.ESCALATE:
            approvers = usecase_demo.APPROVERS.get(decision.resource_id, [])
            case = escalation.open_case(
                decision,
                case_id=str(uuid.uuid4()),
                approver_ids=approvers,
                requester_id=requester.id,
                requested_duration_days=request.requested_duration_days,
            )
            ESCALATIONS[case.id] = case
            _audit(AuditEventType.ESCALATED, actor="policy-engine", detail=decision.reason, request_id=request.id, escalation_id=case.id)
            results.append({"resource_id": decision.resource_id, "status": "escalated", "escalation_id": case.id})

        else:
            _audit(AuditEventType.REQUEST_DENIED, actor="policy-engine", detail=decision.reason, request_id=request.id, payload={"resource_id": decision.resource_id})
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
    if vote.approver_id not in case.required_approver_ids:
        raise HTTPException(403, "not a required approver for this case")
    # TODO(track 5): also require an X-Actor header set by the role picker to match approver_id

    vote = vote.model_copy(update={"escalation_id": escalation_id, "voted_at": now()})
    case = escalation.apply_vote(case, vote)
    ESCALATIONS[escalation_id] = case
    _audit(
        AuditEventType.APPROVAL_VOTE_CAST,
        actor=vote.approver_id,
        detail="approved" if vote.approved else "denied",
        escalation_id=escalation_id,
        request_id=case.request_id,
        payload={"comment": vote.comment} if vote.comment else {},
    )

    if case.status == "approved":
        _issue_grant(case.request_id, case.requester_id, case.resource_id, case.requested_duration_days)

    return case


def _issue_grant(request_id: str, requester_id: str, resource_id: str, ttl_days: int) -> Grant:
    grant = Grant(
        id=str(uuid.uuid4()),
        request_id=request_id,
        resource_id=resource_id,
        requester_id=requester_id,
        granted_at=now(),
        expires_at=now() + timedelta(days=ttl_days),
    )
    GRANTS[grant.id] = grant
    _audit(AuditEventType.GRANT_ISSUED, actor="policy-engine", detail=f"granted {resource_id} for {ttl_days}d", request_id=request_id, grant_id=grant.id)
    return grant


def active_grants(requester_id: str | None = None) -> list[Grant]:
    t = now()
    return [
        g for g in GRANTS.values()
        if not g.revoked and g.expires_at > t and (requester_id is None or g.requester_id == requester_id)
    ]


@app.get("/grants")
def list_grants(requester_id: str | None = None) -> list[Grant]:
    """Active, unexpired grants — what the scoped MCP server derives its tool list from."""
    return active_grants(requester_id)


@app.post("/grants/{grant_id}/revoke")
def revoke_grant(grant_id: str, reason: str = "expired") -> Grant:
    grant = GRANTS.get(grant_id)
    if grant is None:
        raise HTTPException(404, "grant not found")
    if grant.revoked:
        return grant
    grant = grant.model_copy(update={"revoked": True, "revoked_at": now(), "revoked_reason": reason})
    GRANTS[grant_id] = grant
    _audit(AuditEventType.GRANT_REVOKED, actor="policy-engine", detail=reason, grant_id=grant_id, request_id=grant.request_id)
    return grant


@app.post("/projects/{project}/close")
def close_project(project: str) -> dict:
    """The closing beat: every grant tied to `project` is revoked in one action."""
    revoked = []
    for grant in active_grants():
        request = REQUESTS.get(grant.request_id)
        if request is not None and request.project == project:
            revoke_grant(grant.id, reason=f"project {project} closed")
            revoked.append(grant.id)
    _audit(AuditEventType.PROJECT_CLOSED, actor="policy-engine", detail=f"{len(revoked)} grant(s) revoked", payload={"project": project, "grant_ids": revoked})
    return {"project": project, "revoked": revoked}


@app.get("/audit")
def audit_trail(request_id: str | None = None) -> list[AuditEvent]:
    events = AUDIT_LOG
    if request_id:
        events = [e for e in events if e.request_id == request_id]
    return events


@app.get("/audit/verify")
def verify_chain() -> dict:
    """Re-hash the log; report the first index whose prev_hash doesn't match."""
    for i in range(1, len(AUDIT_LOG)):
        if AUDIT_LOG[i].prev_hash != _hash(AUDIT_LOG[i - 1]):
            return {"ok": False, "broken_at": i}
    return {"ok": True, "length": len(AUDIT_LOG)}


@app.get("/ui-spec/{requester_id}")
def ui_spec(requester_id: str) -> UISpec:
    """Current UISpec for a requester from their active grants and pending cases.

    Static mapping for now — the seam where Gemini composes an A2UI-shaped spec
    (track 2 prompt, track 1 renderer). Panel ids are stable so the client can diff.
    """
    grants = active_grants(requester_id)
    pending = [c for c in ESCALATIONS.values() if c.status == "pending" and c.requester_id == requester_id]

    panels = [
        UIComponentSpec(id=f"grant-{g.id}", component="GrantCard", props={"grant_id": g.id, "resource_id": g.resource_id, "expires_at": g.expires_at.isoformat()})
        for g in grants
    ] + [
        UIComponentSpec(id=f"case-{c.id}", component="PendingApprovalCard", props={"escalation_id": c.id, "resource_id": c.resource_id})
        for c in pending
    ]

    return UISpec(requester_id=requester_id, panels=panels)
