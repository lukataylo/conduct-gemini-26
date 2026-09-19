"""
Shared Pydantic contract for the whole system.

Every workstream imports from here instead of redefining its own shapes. If you need a
field that isn't here, add it here and tell the other contributors — don't fork a local
copy, it will drift and nothing will deserialize across service boundaries.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------------------
# Org / resource model (the mocked GCP-style world)
# --------------------------------------------------------------------------------------

class SensitivityTier(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    CRITICAL = "critical"


class ResourceType(str, Enum):
    GCS_BUCKET = "gcs_bucket"
    BIGQUERY_DATASET = "bigquery_dataset"
    CLOUD_SQL_INSTANCE = "cloud_sql_instance"
    IAM_ROLE = "iam_role"


class Resource(BaseModel):
    id: str
    name: str
    type: ResourceType
    owning_team: str
    sensitivity: SensitivityTier
    project: str


class Requester(BaseModel):
    id: str
    name: str
    role: str
    team: str
    manager_id: str | None = None


# --------------------------------------------------------------------------------------
# Requests
# --------------------------------------------------------------------------------------

class AccessRequest(BaseModel):
    id: str
    requester: Requester
    task_description: str
    project: str
    resource_ids: list[str]
    requested_duration_days: int
    raw_text: str | None = None  # original NL input, kept for audit/debugging
    created_at: datetime = Field(default_factory=_utcnow)


# --------------------------------------------------------------------------------------
# Policy engine
# --------------------------------------------------------------------------------------

class DecisionType(str, Enum):
    AUTO_GRANT = "auto_grant"
    AUTO_DENY = "auto_deny"
    ESCALATE = "escalate"


class PolicyRule(BaseModel):
    id: str
    description: str
    # max duration (days) a tier may be auto-granted without escalation
    max_auto_grant_duration_days: dict[SensitivityTier, int]
    # tiers that always escalate regardless of duration
    always_escalate_tiers: set[SensitivityTier] = Field(default_factory=lambda: {SensitivityTier.CRITICAL})
    # approvals required per tier when escalated
    required_approvals: dict[SensitivityTier, int] = Field(
        default_factory=lambda: {
            SensitivityTier.PUBLIC: 0,
            SensitivityTier.INTERNAL: 1,
            SensitivityTier.RESTRICTED: 1,
            SensitivityTier.CRITICAL: 2,
        }
    )
    cross_team_requires_all_owners: bool = True


class PolicyDecision(BaseModel):
    request_id: str
    resource_id: str
    decision: DecisionType
    reason: str
    required_approver_ids: list[str] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=_utcnow)


# --------------------------------------------------------------------------------------
# Escalation / approval queue
# --------------------------------------------------------------------------------------

class ApprovalVote(BaseModel):
    escalation_id: str
    approver_id: str
    approved: bool
    comment: str | None = None
    voted_at: datetime = Field(default_factory=_utcnow)


class EscalationCase(BaseModel):
    id: str
    request_id: str
    resource_id: str
    required_approver_ids: list[str]
    votes: list[ApprovalVote] = Field(default_factory=list)
    status: Literal["pending", "approved", "denied"] = "pending"


# --------------------------------------------------------------------------------------
# Grants
# --------------------------------------------------------------------------------------

class Grant(BaseModel):
    id: str
    request_id: str
    resource_id: str
    requester_id: str
    granted_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime
    revoked: bool = False
    revoked_at: datetime | None = None
    revoked_reason: str | None = None


# --------------------------------------------------------------------------------------
# Audit trail
# --------------------------------------------------------------------------------------

class AuditEventType(str, Enum):
    REQUEST_RECEIVED = "request_received"
    POLICY_EVALUATED = "policy_evaluated"
    ESCALATED = "escalated"
    APPROVAL_VOTE_CAST = "approval_vote_cast"
    GRANT_ISSUED = "grant_issued"
    GRANT_REVOKED = "grant_revoked"
    ACTION_EXECUTED = "action_executed"  # e.g. computer-use action against the console


class AuditEvent(BaseModel):
    id: str
    type: AuditEventType
    actor: str  # "agent" | requester_id | "policy-engine" | approver_id
    detail: str
    request_id: str | None = None
    grant_id: str | None = None
    escalation_id: str | None = None
    payload: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utcnow)


# --------------------------------------------------------------------------------------
# Generative UI contract
# --------------------------------------------------------------------------------------

class UIComponentSpec(BaseModel):
    component: str  # must match a key in generative-ui's component registry
    props: dict = Field(default_factory=dict)


class UISpec(BaseModel):
    requester_id: str
    panels: list[UIComponentSpec]
    generated_at: datetime = Field(default_factory=_utcnow)
