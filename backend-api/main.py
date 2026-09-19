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
import os
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import httpx
from pydantic import BaseModel

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

import gcp_iam  # noqa: E402
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
WATCH_URLS: dict[str, str] = {}
PARSE_IMPL: Callable[[str, Requester], AccessRequest] | None = None
EXECUTE_ENQUEUE_IMPL: Callable[[Grant], None] | None = None
COMPOSE_IMPL: Callable[..., UISpec] | None = None

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


class NLSubmit(BaseModel):
    raw_text: str
    requester_id: str


def _agent_runtime_on_path() -> None:
    root = Path(__file__).resolve().parents[1]
    runtime = str(root / "agent-runtime")
    if runtime not in sys.path:
        sys.path.append(runtime)


def _parse_nl(raw_text: str, requester: Requester) -> AccessRequest:
    if PARSE_IMPL is not None:
        return PARSE_IMPL(raw_text, requester)
    known = list(usecase_demo.RESOURCES)
    url = os.environ.get("AGENT_RUNTIME_PARSE_URL")
    if url:
        try:
            resp = httpx.post(
                url,
                json={
                    "raw_text": raw_text,
                    "requester": requester.model_dump(mode="json"),
                    "known_resource_ids": known,
                },
                timeout=60.0,
            )
            resp.raise_for_status()
            parsed = AccessRequest.model_validate(resp.json())
            return parsed.model_copy(update={"requester": requester, "raw_text": raw_text})
        except Exception as exc:
            raise HTTPException(502, f"parse failed: {exc}") from exc
    _agent_runtime_on_path()
    from gemini_parser import parse_request

    return parse_request(raw_text, requester, known)


def _enqueue_execute(grant: Grant) -> None:
    """Fire-and-forget execute. Models never issue grants; this only enacts one."""
    watch = os.environ.get("AGENT_RUNTIME_WATCH_URL")
    if watch:
        WATCH_URLS[grant.id] = watch
    if EXECUTE_ENQUEUE_IMPL is not None:
        EXECUTE_ENQUEUE_IMPL(grant)
        return
    url = os.environ.get("AGENT_RUNTIME_EXECUTE_URL")
    local = (os.environ.get("AGENT_RUNTIME_LOCAL_EXECUTE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not url and not local:
        return

    def _run() -> None:
        console = os.environ.get("CONSOLE_URL") or "http://127.0.0.1:8765/"
        callback = os.environ.get("BACKEND_PUBLIC_URL") or "http://127.0.0.1:8000"
        payload = {
            "grant": grant.model_dump(mode="json"),
            "console_url": console,
            "callback_base_url": callback,
            "watch_url": watch,
        }
        try:
            if url:
                httpx.post(url, json=payload, timeout=600.0)
                return
            _agent_runtime_on_path()
            from computer_use import execute_grant

            execute_grant(grant, console, watch_url=watch)
        except Exception as exc:
            _audit(
                AuditEventType.ACTION_EXECUTED,
                actor="agent",
                detail=f"execute enqueue failed: {exc}",
                request_id=grant.request_id,
                grant_id=grant.id,
                payload={"phase": "completed", "success": False, "reason": "sandbox_error"},
            )

    threading.Thread(target=_run, daemon=True).start()


@app.post("/requests")
async def submit_request(http_request: Request) -> dict:
    """Accepts NL `{raw_text, requester_id}` or a structured AccessRequest."""
    body = await http_request.json()
    if isinstance(body, dict) and "raw_text" in body and "requester" not in body:
        nl = NLSubmit.model_validate(body)
        requester = KNOWN_REQUESTERS.get(nl.requester_id)
        if requester is None:
            raise HTTPException(400, f"unknown requester '{nl.requester_id}'")
        request = _parse_nl(nl.raw_text, requester)
        request = request.model_copy(update={"requester": requester, "raw_text": nl.raw_text})
    else:
        request = AccessRequest.model_validate(body)
        requester = KNOWN_REQUESTERS.get(request.requester.id)
        if requester is None:
            raise HTTPException(400, f"unknown requester '{request.requester.id}'")
        request = request.model_copy(update={"requester": requester})
    return _evaluate_request(request)


def _evaluate_request(request: AccessRequest) -> dict:
    requester = request.requester
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
            grant = _issue_grant(
                request.id,
                requester.id,
                decision.resource_id,
                ttl_days=request.requested_duration_days,
                ttl_hours=decision.ttl_hours,
            )
            results.append({"resource_id": decision.resource_id, "status": "granted", "grant_id": grant.id})

        elif decision.decision == DecisionType.ESCALATE:
            approvers = usecase_demo.APPROVERS.get(decision.resource_id, [])
            case = escalation.open_case(
                decision,
                case_id=str(uuid.uuid4()),
                approver_ids=approvers,
                requester_id=requester.id,
                requested_duration_days=request.requested_duration_days,
                request=request,
                resource=resources.get(decision.resource_id),
                now=now(),
            )
            ESCALATIONS[case.id] = case
            _audit(AuditEventType.ESCALATED, actor="policy-engine", detail=decision.reason, request_id=request.id, escalation_id=case.id)
            results.append({"resource_id": decision.resource_id, "status": "escalated", "escalation_id": case.id})

        elif decision.decision == DecisionType.STEP_UP_AUTH_REQUIRED:
            results.append({"resource_id": decision.resource_id, "status": "step_up_auth_required", "reason": decision.reason})

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


def _issue_grant(
    request_id: str,
    requester_id: str,
    resource_id: str,
    ttl_days: int | None = None,
    ttl_hours: int | None = None,
) -> Grant:
    ttl = timedelta(hours=ttl_hours) if ttl_hours is not None else timedelta(days=ttl_days or 0)
    grant = Grant(
        id=str(uuid.uuid4()),
        request_id=request_id,
        resource_id=resource_id,
        requester_id=requester_id,
        granted_at=now(),
        expires_at=now() + ttl,
    )
    GRANTS[grant.id] = grant
    ttl_label = f"{ttl_hours}h" if ttl_hours is not None else f"{ttl_days}d"
    _audit(AuditEventType.GRANT_ISSUED, actor="policy-engine", detail=f"granted {resource_id} for {ttl_label}", request_id=request_id, grant_id=grant.id)
    _mirror_to_gcp(grant, add=True)
    _enqueue_execute(grant)
    return grant


def _mirror_to_gcp(grant: Grant, add: bool) -> None:
    """REAL_GCP=true only: apply the grant/revoke to real IAM and log Google's read-back."""
    if not gcp_iam.is_real(grant.resource_id, grant.requester_id):
        return
    result = (gcp_iam.grant if add else gcp_iam.revoke)(grant.resource_id, grant.requester_id)
    if result["verified"]:
        state = "has read access to" if add else "no longer has access to"
        detail = f"Verified in GCP: {result['principal']} {state} {result['resource']}"
    else:
        detail = f"GCP {result['action']} on {result['resource'] or grant.resource_id} not verified: {result.get('error', 'read-back mismatch')}"
    _audit(AuditEventType.ACTION_EXECUTED, actor="gcp-iam", detail=detail, request_id=grant.request_id, grant_id=grant.id, payload=result)


def active_grants(requester_id: str | None = None) -> list[Grant]:
    t = now()
    return [
        g for g in GRANTS.values()
        if not g.revoked and g.expires_at > t and (requester_id is None or g.requester_id == requester_id)
    ]


@app.get("/grants")
def list_grants(requester_id: str | None = None, include_revoked: bool = False) -> list[Grant]:
    """Active, unexpired grants — what the scoped MCP server derives its tool list from.
    include_revoked=true adds revoked/expired ones for the lease timeline."""
    if include_revoked:
        return [g for g in GRANTS.values() if requester_id is None or g.requester_id == requester_id]
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
    # keep real access if another active grant still covers the same requester + resource
    if not any(g.resource_id == grant.resource_id for g in active_grants(grant.requester_id)):
        _mirror_to_gcp(grant, add=False)
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


@app.post("/audit")
def append_audit(event: AuditEvent) -> AuditEvent:
    """Ingest an agent-runtime event; id / prev_hash / timestamp stay server-assigned."""
    return _audit(
        event.type,
        event.actor,
        event.detail,
        request_id=event.request_id,
        grant_id=event.grant_id,
        escalation_id=event.escalation_id,
        payload=event.payload,
        trace_id=event.trace_id,
    )


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
    """A2UI UISpec from compose_ui (catalog-constrained, watch cards when a URL exists)."""
    grants = active_grants(requester_id)
    pending = [c for c in ESCALATIONS.values() if c.status == "pending" and c.requester_id == requester_id]
    watch_urls = {g.id: WATCH_URLS[g.id] for g in grants if g.id in WATCH_URLS}
    if COMPOSE_IMPL is not None:
        return COMPOSE_IMPL(grants, pending, "requester", viewer_id=requester_id, watch_urls=watch_urls)
    url = os.environ.get("AGENT_RUNTIME_COMPOSE_URL")
    if url:
        try:
            resp = httpx.post(
                url,
                json={
                    "grants": [g.model_dump(mode="json") for g in grants],
                    "cases": [c.model_dump(mode="json") for c in pending],
                    "role": "requester",
                    "viewer_id": requester_id,
                    "watch_urls": watch_urls,
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            return UISpec.model_validate(resp.json())
        except Exception:
            pass
    _agent_runtime_on_path()
    from a2ui import compose_ui

    return compose_ui(grants, pending, "requester", viewer_id=requester_id, watch_urls=watch_urls)
