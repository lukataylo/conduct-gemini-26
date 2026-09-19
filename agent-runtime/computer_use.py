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
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from shared.schemas import AuditEvent, AuditEventType, Grant  # noqa: E402

MODEL = "claude-sonnet-5"  # computer-use capable model at build time


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
