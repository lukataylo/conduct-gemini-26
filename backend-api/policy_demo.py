"""
The Friday Finance Freeze — the final-presentation policy story, run for real.

`build_final_story()` seeds the eight scenarios from
usecase-demo/PolicyBasedUserCaseDemo.md (people, resources, business signals), runs each
through the *actual* policy engine (`evaluate_request`, `open_case`,
`review_active_grants`) on a fixed clock, and returns everything the console's Policy
tab shows: the request, the typed decisions, the escalation cards, the reaper's
revocations, and a checklist of the doc's success criteria evaluated against those
outputs.

Read-only and deterministic: it touches no store, writes no audit events, and never
calls a model. The same inputs produce the same JSON every time.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from policy_engine_paths import escalation, policy_engine, usecase_demo
from shared.schemas import (
    AccessContext,
    AccessRequest,
    DecisionType,
    EscalationCase,
    Grant,
    PolicyDecision,
    PolicyEvaluationContext,
    Requester,
    Resource,
    ResourceType,
    RevocationAction,
    SensitivityTier,
)

STORY = "The Friday Finance Freeze"
PRINCIPLE = "AI can parse. Deterministic policy decides."
PROJECT = "atlas-migration"
TICKET = "ATLAS-101"
TOAST = "Access reclaimed: Jira ATLAS-101 is complete."

# Friday afternoon before earnings week. Fixed so every run is reproducible.
DEMO_NOW = datetime(2026, 9, 19, 15, 0, tzinfo=timezone.utc)
QUIET_PERIOD = {
    "start": "2026-09-15T00:00:00Z",
    "end": "2026-10-06T23:59:59Z",
    "label": "Q3 earnings quiet period",
}
WAREHOUSE = {"lat": 51.5000, "lon": -0.1000, "label": "Dagenham DC"}
HOME = {"lat": 51.5074, "lon": -0.1278, "label": "home (Westminster)"}
TEAM_SIZES = {"data-platform": 20, "warehouse-ops": 45}

# --- people -----------------------------------------------------------------------------
# HR heartbeat is checked against the demo clock, so pin the sync time to it.
_HR_SYNC = {"last_hr_sync": DEMO_NOW - timedelta(hours=1)}

ALEX = usecase_demo.REQUESTER.model_copy(update={"role": "Platform Engineer", **_HR_SYNC})
SAM = Requester(
    id="u-contractor-1",
    name="Sam Okafor",
    role="Seasonal Warehouse Contractor",
    team="warehouse-ops",
    type="SEASONAL_CONTRACTOR",
    tenure_days=12,
    manager_id="u-warehouse-lead-1",
    **_HR_SYNC,
)
CFO = Requester(id="u-cfo-1", name="Morgan Reyes", role="Chief Financial Officer", team="finance", **_HR_SYNC)
DATA_STEWARD = Requester(id="u-data-steward-1", name="Ines Fialho", role="Data Steward", team="data-governance", **_HR_SYNC)
JORDAN = usecase_demo.FINANCE_OWNER.model_copy(update=_HR_SYNC)
PEOPLE = [ALEX, SAM, CFO, DATA_STEWARD, JORDAN]

# --- resources --------------------------------------------------------------------------
SECRET_NAMES = ["atlas/db-password", "atlas/stripe-key", "atlas/gcs-hmac", "atlas/slack-webhook"]

RESOURCES: dict[str, Resource] = {
    r.id: r
    for r in [
        Resource(
            id="bucket-runbooks-internal",
            name="platform-runbooks",
            type=ResourceType.GCS_BUCKET,
            owning_team="data-platform",
            sensitivity=SensitivityTier.INTERNAL,
            project=PROJECT,
            capability="read",
        ),
        Resource(
            id="powerbi-revenue-dashboard",
            name="revenue-dashboard",
            type=ResourceType.POWERBI_DATASET,
            owning_team="finance",
            sensitivity=SensitivityTier.RESTRICTED,
            project=PROJECT,
            capability="VIEW",
            metadata={"has_pii": True},
        ),
        Resource(
            id="powerbi-revenue-dataset",
            name="revenue-dataset",
            type=ResourceType.POWERBI_DATASET,
            owning_team="finance",
            sensitivity=SensitivityTier.RESTRICTED,
            project=PROJECT,
            capability="EXPORT",
            metadata={"has_pii": True},
        ),
        Resource(
            id="sql-finance-prod",
            name="finance-prod",
            type=ResourceType.CLOUD_SQL_INSTANCE,
            owning_team="finance",
            sensitivity=SensitivityTier.RESTRICTED,
            project=PROJECT,
            capability="write",
            surface="FINANCE_PROD",
        ),
        Resource(
            id="iot-wms-scanner-07",
            name="wms-scanner-07",
            type=ResourceType.WMS_IOT,
            owning_team="warehouse-ops",
            sensitivity=SensitivityTier.INTERNAL,
            project=PROJECT,
            capability="write",
            category="WMS_IOT",
            metadata={"geofence_center": WAREHOUSE, "geofence_radius_m": 500},
        ),
        Resource(
            id="tool-support-impersonation",
            name="support-impersonation",
            type=ResourceType.IMPERSONATION_TOOL,
            owning_team="support",
            sensitivity=SensitivityTier.RESTRICTED,
            project=PROJECT,
            capability="read",
            metadata={"has_pii": True},
        ),
        *[
            Resource(
                id=f"secret-{i}",
                name=f"vault/{name}",
                type=ResourceType.VAULT_SECRET,
                owning_team="data-platform",
                sensitivity=SensitivityTier.RESTRICTED,
                project=PROJECT,
                capability="read",
            )
            for i, name in enumerate(SECRET_NAMES, start=1)
        ],
    ]
}

APPROVERS: dict[str, list[str]] = {
    "powerbi-revenue-dataset": [DATA_STEWARD.id, JORDAN.id],
    "sql-finance-prod": [CFO.id, JORDAN.id],
}

# --- business signals -------------------------------------------------------------------
JIRA = {
    TICKET: {"status": "IN_PROGRESS", "summary": "Finance dashboard outage — earnings week prep", "assignee": ALEX.id},
    "ATLAS-118": {"status": "IN_PROGRESS", "summary": "Rotate Atlas ingestion credentials", "assignee": ALEX.id},
}
ZENDESK = {
    "ZD-4470": {"requester_email": "customer-b@example.com", "subject": "Invoice PDF missing lines"},
    "ZD-4471": {"requester_email": "customer-a@example.com", "subject": "Dashboard shows stale revenue"},
}
HR = {p.id: {"status": "ACTIVE"} for p in PEOPLE} | {"u-leaver-1": {"status": "LEAVER"}}


def _context(**overrides) -> PolicyEvaluationContext:
    base = {
        "current_date": DEMO_NOW,
        "company_calendar": {"quiet_period": [QUIET_PERIOD]},
        "hr_system": HR,
        "external_signals": {"jira": JIRA, "zendesk": ZENDESK},
    }
    return PolicyEvaluationContext(**{**base, **overrides})


def _request(
    who: Requester,
    resource_ids: list[str],
    task: str,
    *,
    days: int = 1,
    ticket: str | None = TICKET,
    metadata: dict | None = None,
    location: str | None = None,
) -> AccessRequest:
    return AccessRequest(
        id=f"req-{'-'.join(resource_ids[:1])}",
        requester=who,
        task_description=task,
        project=PROJECT,
        resource_ids=resource_ids,
        requested_duration_days=days,
        context=AccessContext(active_jira_ticket=ticket, location=location),
        metadata=metadata or {},
        raw_text=task,
        created_at=DEMO_NOW,
    )


def _grant(gid: str, who: Requester, resource_id: str, *, capability: str, ticket: str, minutes_ago: int, hours_left: int, **meta) -> Grant:
    return Grant(
        id=gid,
        request_id=f"req-{gid}",
        resource_id=resource_id,
        requester_id=who.id,
        capability=capability,
        metadata={"ticket_id": ticket, **meta},
        granted_at=DEMO_NOW - timedelta(minutes=minutes_ago),
        expires_at=DEMO_NOW + timedelta(hours=hours_left),
    )


# --- one scenario through the engine ----------------------------------------------------

def _evaluate(
    request: AccessRequest,
    *,
    context: PolicyEvaluationContext | None = None,
    active_grants: list[Grant] | None = None,
) -> tuple[list[PolicyDecision], list[EscalationCase]]:
    ctx = context or _context()
    decisions = [
        # evaluated_at is the engine's wall-clock stamp, the one thing not derived from inputs;
        # pin it to the demo clock so the story is byte-for-byte reproducible.
        d.model_copy(update={"evaluated_at": DEMO_NOW})
        for d in policy_engine.evaluate_request(
            request,
            RESOURCES,
            active_grants=active_grants or [],
            context=ctx,
            team_size_by_team=TEAM_SIZES,
            now=DEMO_NOW,
        )
    ]
    cases = []
    for d in decisions:
        if d.decision not in {DecisionType.ESCALATE, DecisionType.WITNESS_REQUIRED}:
            continue
        cases.append(
            escalation.open_case(
                d,
                case_id=f"case-{d.resource_id}",
                approver_ids=APPROVERS.get(d.resource_id, [JORDAN.id]),
                requester_id=request.requester.id,
                requested_duration_days=request.requested_duration_days,
                request=request,
                resource=RESOURCES.get(d.resource_id),
                now=DEMO_NOW,
            )
        )
    return decisions, cases


def _ticket_context(request: AccessRequest) -> dict:
    ticket = request.metadata.get("ticket_id") or request.context.active_jira_ticket
    incident = request.metadata.get("incident_id") or request.context.active_pagerduty_incident
    source = "zendesk" if ticket and ticket.startswith("ZD-") else "jira" if ticket else "pagerduty" if incident else None
    signal = (ZENDESK if source == "zendesk" else JIRA).get(ticket, {}) if ticket else {}
    return {"ticket_id": ticket, "incident_id": incident, "source": source, "signal": signal}


def _scenario(
    *,
    id: str,
    beat: int,
    title: str,
    narrative: str,
    request: AccessRequest,
    context: PolicyEvaluationContext | None = None,
    active_grants: list[Grant] | None = None,
) -> dict:
    ctx = context or _context()
    decisions, cases = _evaluate(request, context=ctx, active_grants=active_grants)
    resources = [RESOURCES[rid] for rid in request.resource_ids if rid in RESOURCES]
    return {
        "id": id,
        "beat": beat,
        "kind": "request",
        "title": title,
        "narrative": narrative,
        "requester": request.requester.model_dump(mode="json"),
        "resources": [r.model_dump(mode="json") for r in resources],
        "request": request.model_dump(mode="json"),
        "ticket": _ticket_context(request),
        "context": ctx.model_dump(mode="json"),
        "context_snapshot": policy_engine._context_snapshot(ctx),
        "compliance": sorted({c for r in resources for c in policy_engine._compliance_checks(r)}),
        "active_grants": [g.model_dump(mode="json") for g in (active_grants or [])],
        "decisions": [d.model_dump(mode="json") for d in decisions],
        "cases": [c.model_dump(mode="json") for c in cases],
        "_decisions": decisions,
        "_cases": cases,
    }


# --- the eight beats --------------------------------------------------------------------

def _beat_1() -> dict:
    return _scenario(
        id="safe-internal-access",
        beat=1,
        title="Safe Internal Access",
        narrative="Alex has Jira ATLAS-101 and asks to read the platform runbooks. Same team, internal tier, read only: the engine grants it with a TTL and no human in the loop.",
        request=_request(ALEX, ["bucket-runbooks-internal"], "Read the platform runbooks to triage the finance dashboard outage."),
    )


def _beat_2() -> dict:
    return _scenario(
        id="powerbi-view-vs-export",
        beat=2,
        title="PowerBI View vs Export",
        narrative="One request, two capabilities. Viewing the revenue dashboard auto-grants; exporting the underlying dataset escalates to the Data Steward, and because it holds PII both carry DISABLE_EXPORT.",
        request=_request(
            ALEX,
            ["powerbi-revenue-dashboard", "powerbi-revenue-dataset"],
            "Check the revenue dashboard and pull the dataset to compare against the pipeline output.",
        ),
    )


def _beat_3() -> dict:
    return _scenario(
        id="earnings-quiet-period",
        beat=3,
        title="Earnings Quiet Period",
        narrative="Alex asks for write access to finance production. The company calendar says earnings quiet period: the engine downgrades the ask to read-only and escalates to the CFO with SOX-404 on the record.",
        request=_request(ALEX, ["sql-finance-prod"], "Patch the revenue rollup job in finance-prod so the dashboard recovers."),
    )


def _beat_4() -> dict:
    return _scenario(
        id="warehouse-geofence-deny",
        beat=4,
        title="Warehouse Geofence Deny",
        narrative="A seasonal contractor tries to control a warehouse scanner from home. The scanner has a 500 m geofence around the depot; the requester is 2 km away. Physical presence is required, so it is denied outright.",
        request=_request(
            SAM,
            ["iot-wms-scanner-07"],
            "Re-pair scanner 07 on the inbound dock before the Monday shift.",
            ticket="WMS-772",
            location=HOME["label"],
        ),
        context=_context(requester_location=HOME, external_signals={"jira": {**JIRA, "WMS-772": {"status": "IN_PROGRESS", "summary": "Scanner 07 pairing"}}, "zendesk": ZENDESK}),
    )


def _beat_5() -> dict:
    return _scenario(
        id="support-impersonation-mismatch",
        beat=5,
        title="Support Impersonation Mismatch",
        narrative="Alex tries to impersonate customer B, citing Zendesk ZD-4471. That ticket was raised by customer A. The ticket requester must match the target, so the engine hard-denies under GDPR Art. 32.",
        request=_request(
            ALEX,
            ["tool-support-impersonation"],
            "Impersonate the customer on ZD-4471 to reproduce the stale dashboard they reported.",
            ticket=None,
            metadata={"ticket_id": "ZD-4471", "target_user_email": "customer-b@example.com"},
        ),
    )


def _beat_6() -> dict:
    recent = [
        _grant(f"grant-secret-{i}", ALEX, f"secret-{i}", capability="read", ticket="ATLAS-118", minutes_ago=10 * (4 - i), hours_left=1)
        for i in (1, 2, 3)
    ]
    return _scenario(
        id="secret-harvesting-alarm",
        beat=6,
        title="Secret Harvesting Alarm",
        narrative="Alex already pulled three vault secrets in the last half hour and asks for a fourth. A fourth unique secret inside 60 minutes trips the harvesting threshold: denied, with an anomaly alarm raised.",
        request=_request(ALEX, ["secret-4"], "Need the Slack webhook secret to post pipeline alerts.", ticket="ATLAS-118"),
        active_grants=recent,
    )


def _beat_7() -> dict:
    return _scenario(
        id="evidence-based-escalation-card",
        beat=7,
        title="Evidence-Based Escalation Card",
        narrative="The same quiet-period rule, but look at what the approver gets: the policy violated, a risk score, how many peers hold this access, a suggested downgrade, who must approve, and the SLA clock. A one-click decision with evidence, not a rubber stamp.",
        request=_request(
            ALEX,
            ["sql-finance-prod"],
            "Two weeks of write access to finance-prod to finish the rollup migration before earnings.",
            days=14,
        ),
    )


def _beat_8() -> dict:
    finance = _grant(
        "grant-finance-atlas-101",
        ALEX,
        "sql-finance-prod",
        capability="read",
        ticket=TICKET,
        minutes_ago=120,
        hours_left=22,
        approved_by=CFO.id,
        restriction="READ_ONLY",
    )
    other = _grant("grant-secret-1", ALEX, "secret-1", capability="read", ticket="ATLAS-118", minutes_ago=30, hours_left=1)
    grants = [finance, other]

    before_ctx = _context()
    after_ctx = _context(external_signals={"jira": {**JIRA, TICKET: {**JIRA[TICKET], "status": "DONE"}}, "zendesk": ZENDESK})
    before = policy_engine.review_active_grants(grants, RESOURCES, before_ctx)
    after = policy_engine.review_active_grants(grants, RESOURCES, after_ctx)

    def state(label: str, ctx: PolicyEvaluationContext, revocations: list[RevocationAction]) -> dict:
        revoked = {r.grant_id: r for r in revocations}
        return {
            "label": label,
            "jira": ctx.external_signals["jira"][TICKET],
            "grants": [
                {**g.model_dump(mode="json"), "reclaimed": g.id in revoked, "reclaim_reason": revoked[g.id].reason if g.id in revoked else None}
                for g in grants
            ],
            "revocations": [r.model_dump(mode="json") for r in revocations],
            "context_snapshot": policy_engine._context_snapshot(ctx),
            "toast": TOAST if revocations else None,
        }

    return {
        "id": "reaper-atlas-101-done",
        "beat": 8,
        "kind": "reaper",
        "title": "Reaper: Jira ATLAS-101 Done → Auto-Revoke",
        "narrative": "The CFO approved read-only finance access for ATLAS-101 two hours ago; 22 hours remain on the TTL. The presenter marks ATLAS-101 DONE. The Reaper reviews every live grant against the ticket system and reclaims the finance grant immediately, leaving the unrelated ATLAS-118 grant untouched.",
        "requester": ALEX.model_dump(mode="json"),
        "resources": [RESOURCES[g.resource_id].model_dump(mode="json") for g in grants],
        "ticket": {"ticket_id": TICKET, "incident_id": None, "source": "jira", "signal": JIRA[TICKET]},
        "context": before_ctx.model_dump(mode="json"),
        "compliance": sorted(policy_engine._compliance_checks(RESOURCES["sql-finance-prod"])),
        "before": state("ATLAS-101 in progress", before_ctx, before),
        "after": state("ATLAS-101 done", after_ctx, after),
        "toast": TOAST,
        "_before": before,
        "_after": after,
    }


# --- success criteria (usecase-demo/PolicyBasedUserCaseDemo.md) ---------------------------

_MODEL_SDKS = ("google.genai", "google.generativeai", "anthropic", "openai", "pydantic_ai", "httpx", "requests", "vertexai")


def _engine_is_model_free() -> tuple[bool, str]:
    src = (Path(__file__).resolve().parents[1] / "policy-engine" / "engine.py").read_text()
    imported = {m.group(1) for m in re.finditer(r"^\s*(?:from|import)\s+([\w.]+)", src, re.M)}
    hits = sorted(i for i in imported if any(i == s or i.startswith(s + ".") for s in _MODEL_SDKS))
    return (not hits, "engine.py imports no model SDK or HTTP client" if not hits else f"engine.py imports {', '.join(hits)}")


def _checks(by_id: dict[str, dict]) -> list[dict]:
    def one(sid: str, i: int = 0) -> PolicyDecision:
        return by_id[sid]["_decisions"][i]

    def case(sid: str, i: int = 0) -> EscalationCase:
        return by_id[sid]["_cases"][i]

    s1, view, export = one("safe-internal-access"), one("powerbi-view-vs-export", 0), one("powerbi-view-vs-export", 1)
    quiet, geo, imp, secret = one("earnings-quiet-period"), one("warehouse-geofence-deny"), one("support-impersonation-mismatch"), one("secret-harvesting-alarm")
    card = case("evidence-based-escalation-card")
    reaper = by_id["reaper-atlas-101-done"]
    after_ids = [r.grant_id for r in reaper["_after"]]
    model_free, model_detail = _engine_is_model_free()

    checks = [
        ("Safe internal access auto-grants", s1.decision == DecisionType.AUTO_GRANT and s1.ttl_hours is not None, s1.reason),
        (
            "PowerBI view grants and export escalates",
            view.decision == DecisionType.AUTO_GRANT and export.decision == DecisionType.ESCALATE and "data_steward" in export.required_approval_groups and export.metadata.get("restriction") == "DISABLE_EXPORT",
            f"view → {view.decision.value}; export → {export.decision.value} to {', '.join(export.required_approval_groups)}; {export.metadata.get('restriction')}",
        ),
        (
            "Finance write during quiet period escalates to CFO and becomes read-only",
            quiet.decision == DecisionType.ESCALATE and "cfo" in quiet.required_approval_groups and quiet.metadata.get("downgraded_capability") == "read" and "SOX-404" in quiet.metadata.get("compliance_checked", []),
            f"{quiet.decision.value} to {', '.join(quiet.required_approval_groups)}; write → {quiet.metadata.get('downgraded_capability')}; {', '.join(quiet.metadata.get('compliance_checked', []))}",
        ),
        ("Warehouse IoT access from outside the geofence is denied", geo.decision == DecisionType.AUTO_DENY and geo.metadata.get("policy_violation") == "Warehouse Geofence", geo.reason),
        ("Support impersonation mismatch is denied", imp.decision == DecisionType.AUTO_DENY and imp.metadata.get("policy_violation") == "Support Impersonation Mismatch", imp.reason),
        ("Secret harvesting is denied with anomaly alarm", secret.decision == DecisionType.AUTO_DENY and secret.metadata.get("anomaly_alarm") is True, secret.reason),
        (
            "Escalation card shows risk, violation, peer signal, downgrade, approvers, and SLA",
            all([card.risk_score, card.policy_violation, card.peer_percentile, card.suggested_downgrade, card.required_approver_ids, card.sla_due_at]),
            f"risk {card.risk_score}; {card.policy_violation}; {card.peer_percentile}; {card.suggested_downgrade}; approvers {', '.join(card.required_approver_ids)}; SLA {card.sla_due_at.isoformat() if card.sla_due_at else None}",
        ),
        (
            "Reaper revokes the finance grant when Jira ATLAS-101 is marked DONE",
            not reaper["_before"] and after_ids == ["grant-finance-atlas-101"] and reaper["_after"][0].metadata.get("reaper_trigger") == "justification_sunset",
            f"before: {len(reaper['_before'])} revocation(s); after: {after_ids}",
        ),
        ("AI can parse; deterministic policy decides", model_free, model_detail),
    ]
    return [{"name": n, "ok": bool(ok), "detail": d} for n, ok, d in checks]


def build_final_story() -> dict:
    scenarios = [_beat_1(), _beat_2(), _beat_3(), _beat_4(), _beat_5(), _beat_6(), _beat_7(), _beat_8()]
    by_id = {s["id"]: s for s in scenarios}
    checks = _checks(by_id)
    public = [{k: v for k, v in s.items() if not k.startswith("_")} for s in scenarios]
    return {
        "story": STORY,
        "principle": PRINCIPLE,
        "demo_now": DEMO_NOW.isoformat(),
        "quiet_period": QUIET_PERIOD,
        "engine": {
            "module": "policy-engine/engine.py",
            "entry_points": ["evaluate_request", "review_active_grants", "escalation.open_case"],
            "model_calls": 0,
        },
        "people": [p.model_dump(mode="json") for p in PEOPLE],
        "scenarios": public,
        "checks": checks,
        "all_pass": all(c["ok"] for c in checks),
    }
