"""
Executes the *visible* part of the demo: once a Grant is issued, an agent using Claude's
computer-use tool actually operates the mock GCP console UI (clicks "Grant access",
types the scope, hits confirm) instead of the backend silently flipping a boolean. This
is the on-stage "wow" moment — the agent is *seen* doing the privileged action, and every
action it takes is logged as an AuditEvent(type=ACTION_EXECUTED).

Keep this isolated from policy-engine: computer-use only ever *executes* a decision
that's already been made (auto-grant or approved-escalation). It never decides.
"""
from __future__ import annotations

import os
import sys
import uuid
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

sys.path.append(str(Path(__file__).resolve().parents[1]))

import audit_logger  # noqa: E402
from shared.schemas import AuditEvent, AuditEventType, Grant  # noqa: E402

MODEL = "claude-sonnet-5"  # computer-use capable model at build time

DEFAULT_CONSOLE_HOSTS = ("127.0.0.1", "localhost")
FAILURE_REASONS = frozenset(
    {
        "turn_budget",
        "blocked",
        "verify_failed",
        "sandbox_error",
        "gemini_unavailable",
        "unknown_host",
    }
)


def grant_goal(grant: Grant) -> str:
    """Instruction for computer-use: enact this grant and no other."""
    expiry = grant.expires_at.date().isoformat()
    return (
        f"Grant access to {grant.resource_id} for principal {grant.requester_id} "
        f"expiring {expiry}. Do not grant any other resource."
    )


def host_allowed(console_url: str, allowlist: list[str] | None = None) -> bool:
    """True when the console URL's hostname is on the allowlist."""
    hosts = allowlist if allowlist is not None else list(DEFAULT_CONSOLE_HOSTS)
    hostname = (urlparse(console_url).hostname or "").lower()
    if not hostname:
        return False
    allowed = {h.lower() for h in hosts}
    return hostname in allowed


class _ActiveGrantScanner(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.entries: list[tuple[str | None, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "li":
            return
        data = dict(attrs)
        self.entries.append((data.get("data-resource"), data.get("data-principal")))


def verify_active(html: str, grant: Grant) -> bool:
    """True when #active-grants HTML lists this grant's resource and principal."""
    scanner = _ActiveGrantScanner()
    scanner.feed(html)
    return any(
        resource == grant.resource_id and principal == grant.requester_id
        for resource, principal in scanner.entries
    )


def completed_event(
    grant: Grant,
    *,
    success: bool,
    reason: str | None,
    actions: list,
    watch_url: str | None,
    mode: str,
    turn_count: int,
) -> AuditEvent:
    """Emit and return the completed ACTION_EXECUTED event for a grant run."""
    if success:
        if reason is not None:
            raise ValueError("reason must be None when success=True")
    elif reason not in FAILURE_REASONS:
        raise ValueError(
            f"reason must be one of {sorted(FAILURE_REASONS)} or None when success=True"
        )

    detail = (
        f"completed grant {grant.resource_id}"
        if success
        else f"grant execution failed: {reason}"
    )
    return audit_logger.log(
        AuditEventType.ACTION_EXECUTED,
        actor="agent",
        detail=detail,
        request_id=grant.request_id,
        grant_id=grant.id,
        payload={
            "phase": "completed",
            "success": success,
            "reason": reason,
            "actions": actions,
            "watch_url": watch_url,
            "mode": mode,
            "turn_count": turn_count,
        },
    )


def execute_grant(grant: Grant, console_url: str) -> AuditEvent:
    """Drive the mock console (via computer-use) to actually perform `grant`.

    NOTE: skeleton. Wire up the real Anthropic computer-use loop here:

      1. Launch/attach to a browser or virtual display pointed at `console_url`
         (the mock GCP console from usecase-demo / backend-api).
      2. Give Claude the computer-use tool + a goal derived from `grant`
         (resource_id, requester_id, expires_at).
      3. Loop on tool_use blocks (screenshot / click / type / key) until the console
         shows the grant as active, or a turn budget is exhausted.
      4. Return an AuditEvent describing what was done (and ideally a screenshot path
         in `payload` for the UI to show "proof of work").

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    """
    raise NotImplementedError("wire up the Anthropic computer-use tool loop here")


def _action_event(grant: Grant, detail: str, payload: dict | None = None) -> AuditEvent:
    return AuditEvent(
        id=str(uuid.uuid4()),
        type=AuditEventType.ACTION_EXECUTED,
        actor="agent",
        detail=detail,
        grant_id=grant.id,
        request_id=grant.request_id,
        payload=payload or {},
    )
