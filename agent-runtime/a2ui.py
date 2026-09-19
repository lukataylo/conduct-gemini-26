"""Compose an A2UI-shaped UISpec against a fixed component catalog."""
from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from envutil import gemini_api_key  # noqa: E402
from shared.schemas import EscalationCase, Grant, UIComponentSpec, UISpec  # noqa: E402

CATALOG = ("GrantCard", "PendingApprovalCard", "AuditTimeline", "ConsoleWatchCard")

COMPOSE_PROMPT = """You compose an A2UI UISpec from a viewer's grants and escalation cases.
Only use these component names: GrantCard, PendingApprovalCard, AuditTimeline, ConsoleWatchCard.
Use stable panel ids: grant-{grant.id}, case-{case.id}, audit-{viewer_id}, watch-{grant.id}.
Do not invent grant_id or escalation_id values that are not in the provided set.
"""

_LOGFIRE_READY = False


def _ensure_logfire() -> None:
    global _LOGFIRE_READY
    if _LOGFIRE_READY:
        return
    import logfire

    logfire.configure(send_to_logfire="if-token-present")
    logfire.instrument_pydantic_ai()
    _LOGFIRE_READY = True


def _default_runner(prompt: str) -> UISpec:
    from pydantic_ai import Agent

    key = gemini_api_key()
    os.environ.setdefault("GOOGLE_API_KEY", key)
    os.environ.setdefault("GEMINI_API_KEY", key)
    _ensure_logfire()
    agent = Agent(
        "google-gla:gemini-2.5-flash",
        output_type=UISpec,
        system_prompt=COMPOSE_PROMPT,
    )
    result = agent.run_sync(prompt)
    return result.output


def _is_active(grant: Grant, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if grant.revoked:
        return False
    expires = grant.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > now


def _grant_card(grant: Grant) -> UIComponentSpec:
    return UIComponentSpec(
        id=f"grant-{grant.id}",
        component="GrantCard",
        props={
            "grant_id": grant.id,
            "resource_id": grant.resource_id,
            "expires_at": grant.expires_at.isoformat(),
        },
    )


def _case_card(case: EscalationCase) -> UIComponentSpec:
    return UIComponentSpec(
        id=f"case-{case.id}",
        component="PendingApprovalCard",
        props={
            "escalation_id": case.id,
            "resource_id": case.resource_id,
        },
    )


def _fallback(
    grants: Iterable[Grant],
    cases: Iterable[EscalationCase],
    role: str,
    viewer_id: str,
) -> UISpec:
    active = [g for g in grants if _is_active(g)]
    pending = [c for c in cases if c.status == "pending"]
    panels: list[UIComponentSpec] = []
    if role == "requester":
        mine = [g for g in active if g.requester_id == viewer_id]
        my_cases = [c for c in pending if c.requester_id == viewer_id]
        panels = [_grant_card(g) for g in mine] + [_case_card(c) for c in my_cases]
    elif role == "approver":
        mine = [c for c in pending if viewer_id in c.required_approver_ids]
        panels = [_case_card(c) for c in mine] + [_grant_card(g) for g in active]
    elif role == "auditor":
        panels = [
            UIComponentSpec(id=f"audit-{viewer_id}", component="AuditTimeline", props={}),
            *(_grant_card(g) for g in active),
        ]
    return UISpec(requester_id=viewer_id, panels=panels)


def _sanitize(
    panels: list[UIComponentSpec],
    grants: Iterable[Grant],
    cases: Iterable[EscalationCase],
) -> list[UIComponentSpec]:
    grant_ids = {g.id for g in grants}
    case_ids = {c.id for c in cases}
    kept: list[UIComponentSpec] = []
    for panel in panels:
        if panel.component not in CATALOG:
            continue
        grant_id = panel.props.get("grant_id")
        escalation_id = panel.props.get("escalation_id")
        if grant_id is not None and grant_id not in grant_ids:
            continue
        if escalation_id is not None and escalation_id not in case_ids:
            continue
        kept.append(panel)
    return kept


def _prompt(
    grants: Iterable[Grant],
    cases: Iterable[EscalationCase],
    role: str,
    viewer_id: str,
) -> str:
    grant_payload = [g.model_dump(mode="json") for g in grants]
    case_payload = [c.model_dump(mode="json") for c in cases]
    return (
        f"{COMPOSE_PROMPT}\n"
        f"Role: {role}\n"
        f"Viewer: {viewer_id}\n"
        f"Catalog: {', '.join(CATALOG)}\n"
        f"Grants: {grant_payload}\n"
        f"Cases: {case_payload}\n"
    )


def compose_ui(
    grants: list[Grant],
    cases: list[EscalationCase],
    role: str,
    *,
    viewer_id: str,
    runner: Callable[[str], UISpec] | None = None,
) -> UISpec:
    """Return a catalog-constrained UISpec. Missing/raising runner uses fallback."""
    if runner is None:
        spec = _fallback(grants, cases, role, viewer_id)
    else:
        try:
            spec = runner(_prompt(grants, cases, role, viewer_id))
        except Exception:
            spec = _fallback(grants, cases, role, viewer_id)
    return spec.model_copy(update={"panels": _sanitize(spec.panels, grants, cases)})
