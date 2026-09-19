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
    GITHUB_REPO = "github_repo"
    GITHUB_REPO_UPPER = "GITHUB_REPO"
    POWERBI_DATASET = "powerbi_dataset"
    POWERBI_DATASET_UPPER = "POWERBI_DATASET"
    PAYMENT_RAIL = "payment_rail"
    PAYMENT_RAIL_UPPER = "PAYMENT_RAIL"
    WMS_IOT = "wms_iot"
    WMS_IOT_UPPER = "WMS_IOT"
    IMPERSONATION_TOOL = "impersonation_tool"
    IMPERSONATION_TOOL_UPPER = "IMPERSONATION_TOOL"
    BUILD_PIPELINE = "build_pipeline"
    BUILD_PIPELINE_UPPER = "BUILD_PIPELINE"
    VAULT_SECRET = "vault_secret"
    VAULT_SECRET_UPPER = "VAULT_SECRET"


class AuthType(str, Enum):
    FIDO2_MFA = "fido2_mfa"
    PASSKEY = "passkey"
    HARDWARE_TOKEN = "hardware_token"
    TOTP_MFA = "totp_mfa"
    PASSWORD = "password"


class Resource(BaseModel):
    id: str
    name: str
    type: ResourceType
    owning_team: str
    sensitivity: SensitivityTier
    project: str
    capability: Literal[
        "read",
        "write",
        "delete",
        "shutdown",
        "drop",
        "terminate",
        "iam_change",
        "admin",
        "ADMIN",
        "view",
        "VIEW",
        "export",
        "EXPORT",
        "power_query",
        "POWER_QUERY",
    ] = "read"
    target: str | None = None
    surface: str | None = None
    category: str | None = None
    metadata: dict = Field(default_factory=dict)
    owner_group: str | None = None


class Requester(BaseModel):
    id: str
    name: str
    role: str
    team: str
    manager_id: str | None = None
    manager_email: str | None = None
    is_active: bool = True
    is_active_employee: bool = True
    is_on_call: bool = False
    identity_type: Literal["human", "agent"] = "human"
    type: str = "EMPLOYEE"
    tenure_days: int = Field(default=365, ge=0)
    last_hr_sync: datetime = Field(default_factory=_utcnow)
    risk_score: int = Field(default=0, ge=0, le=100)
    auth_type: AuthType = AuthType.FIDO2_MFA


class AccessContext(BaseModel):
    device_compliant: bool = True
    location_anomaly: bool = False
    active_jira_ticket: str | None = None
    active_pagerduty_incident: str | None = None
    location: str | None = None
    justification_provided: str | None = None


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
    context: AccessContext = Field(default_factory=AccessContext)
    metadata: dict = Field(default_factory=dict)
    raw_text: str | None = None  # original NL input, kept for audit/debugging
    created_at: datetime = Field(default_factory=_utcnow)


class PolicyEvaluationContext(BaseModel):
    company_calendar: dict = Field(default_factory=dict)
    requester_location: dict = Field(default_factory=dict)
    external_signals: dict = Field(default_factory=dict)
    hr_system: dict = Field(default_factory=dict)
    current_date: datetime = Field(default_factory=_utcnow)


# --------------------------------------------------------------------------------------
# Policy engine
# --------------------------------------------------------------------------------------

class DecisionType(str, Enum):
    AUTO_GRANT = "auto_grant"
    AUTO_DENY = "auto_deny"
    ESCALATE = "escalate"
    STEP_UP_AUTH_REQUIRED = "step_up_auth_required"
    WITNESS_REQUIRED = "witness_required"


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
    ttl_hours: int | None = None
    audit_tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    required_approver_ids: list[str] = Field(default_factory=list)
    required_approval_groups: list[str] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=_utcnow)


class RequestHistoryEvent(BaseModel):
    requester_id: str
    resource_id: str
    decision: DecisionType
    reason: str | None = None
    timestamp: datetime = Field(default_factory=_utcnow)


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
    # Snapshot at open time so a later re-POST of the request can't change who gets
    # the grant or for how long once approvers have voted.
    requester_id: str
    requested_duration_days: int
    votes: list[ApprovalVote] = Field(default_factory=list)
    escalation_reason: str | None = None
    human_summary: str | None = None
    routing_rationale: str | None = None
    peer_percentile: str | None = None
    risk_score: str | None = None
    policy_violation: str | None = None
    suggested_downgrade: str | None = None
    metadata: dict = Field(default_factory=dict)
    opened_at: datetime = Field(default_factory=_utcnow)
    sla_due_at: datetime | None = None
    timeout_action: Literal["auto_deny", "default_escalate"] = "auto_deny"
    status: Literal["pending", "approved", "denied"] = "pending"


# --------------------------------------------------------------------------------------
# Grants
# --------------------------------------------------------------------------------------

class Grant(BaseModel):
    id: str
    request_id: str
    resource_id: str
    requester_id: str
    capability: str | None = None
    metadata: dict = Field(default_factory=dict)
    granted_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime
    revoked: bool = False
    revoked_at: datetime | None = None
    revoked_reason: str | None = None


class RevocationAction(BaseModel):
    grant_id: str
    requester_id: str
    resource_id: str
    reason: str
    metadata: dict = Field(default_factory=dict)
    decided_at: datetime = Field(default_factory=_utcnow)


# --------------------------------------------------------------------------------------
# Audit trail
# --------------------------------------------------------------------------------------

class AuditEventType(str, Enum):
    REQUEST_RECEIVED = "request_received"
    POLICY_EVALUATED = "policy_evaluated"
    ESCALATED = "escalated"
    APPROVAL_VOTE_CAST = "approval_vote_cast"
    REQUEST_DENIED = "request_denied"
    GRANT_ISSUED = "grant_issued"
    GRANT_REVOKED = "grant_revoked"
    PROJECT_CLOSED = "project_closed"
    ACTION_EXECUTED = "action_executed"  # e.g. an MCP tool call or a computer-use action


class AuditEvent(BaseModel):
    id: str
    type: AuditEventType
    actor: str  # "agent" | requester_id | "policy-engine" | approver_id
    detail: str
    request_id: str | None = None
    grant_id: str | None = None
    escalation_id: str | None = None
    payload: dict = Field(default_factory=dict)
    trace_id: str | None = None  # Logfire span for model-produced events
    prev_hash: str | None = None  # sha256 of the previous event; server-assigned
    timestamp: datetime = Field(default_factory=_utcnow)


# --------------------------------------------------------------------------------------
# Generative UI contract
# --------------------------------------------------------------------------------------

class UIComponentSpec(BaseModel):
    id: str  # stable across regenerations so the client can diff instead of replace
    component: str  # must match a key in generative-ui's component registry
    props: dict = Field(default_factory=dict)


class UISpec(BaseModel):
    requester_id: str
    panels: list[UIComponentSpec]
    generated_at: datetime = Field(default_factory=_utcnow)
