"""
Thin, typed logging helper: every function in this package should emit AuditEvents
through here rather than ad-hoc print()/logging calls, so backend-api's audit trail
(and thus the demo's "trust" UI panel) is complete and structured.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Callable

sys.path.append(str(Path(__file__).resolve().parents[1]))

from shared.schemas import AuditEvent, AuditEventType  # noqa: E402

# Swap this for a real sink (HTTP POST to backend-api, a queue, a DB write) once
# backend-api exposes an /audit endpoint. Defaults to a local in-memory list + stdout so
# this package is independently testable without the rest of the stack running.
_sink: list[AuditEvent] = []
_emit: Callable[[AuditEvent], None] | None = None


def set_emitter(fn: Callable[[AuditEvent], None]) -> None:
    """Point audit events at a real sink, e.g. a POST to backend-api's /audit endpoint."""
    global _emit
    _emit = fn


def reset() -> None:
    global _emit
    _sink.clear()
    _emit = None


def log(
    type: AuditEventType,
    actor: str,
    detail: str,
    *,
    request_id: str | None = None,
    grant_id: str | None = None,
    escalation_id: str | None = None,
    payload: dict | None = None,
    trace_id: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        id=str(uuid.uuid4()),
        type=type,
        actor=actor,
        detail=detail,
        request_id=request_id,
        grant_id=grant_id,
        escalation_id=escalation_id,
        payload=payload or {},
        trace_id=trace_id,
    )
    _sink.append(event)
    print(f"[audit] {event.type.value} actor={event.actor} detail={event.detail}")
    if _emit:
        _emit(event)
    return event


def local_events() -> list[AuditEvent]:
    """For local dev/tests only — real consumers should read from backend-api."""
    return list(_sink)
