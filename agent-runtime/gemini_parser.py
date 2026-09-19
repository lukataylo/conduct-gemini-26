"""
Parses a free-text access request into a structured AccessRequest using Gemini's
structured-output mode (response_schema). This is the ONLY place natural language
touches the request pipeline — everything downstream (policy-engine) is typed.
"""
from __future__ import annotations

import os
import re
import sys
import uuid
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

sys.path.append(str(Path(__file__).resolve().parents[1]))

from envutil import gemini_api_key  # noqa: E402
from shared.schemas import AccessRequest, Requester  # noqa: E402

MODEL = "gemini-2.5-flash"  # swap for whatever's current at build time

PARSE_PROMPT = """You are extracting a structured access request from an employee's
(or their coding agent's) free-text message. Identify:
- which resource names/ids they're asking for
- the project this work belongs to
- how many days they need access for (infer a reasonable default like 14 if unstated)
Respond only with the fields asked for in the schema.
"""


class ParseFields(BaseModel):
    project: str = "atlas-migration"
    resource_ids: list[str] = Field(default_factory=list)
    requested_duration_days: int | None = None


def constrain_resource_ids(ids: list[str], known: list[str]) -> list[str]:
    known_set = set(known)
    out: list[str] = []
    for item in ids:
        if item in known_set and item not in out:
            out.append(item)
    return out


def duration_days(raw_text: str, parsed_days: int | None, *, today: date | None = None) -> int:
    if parsed_days is not None and parsed_days > 0:
        return parsed_days
    today = today or date.today()
    match = re.search(
        r"done by\s+([A-Za-z]{3,9}\s+\d{1,2}(?:,\s*\d{4})?)",
        raw_text,
        flags=re.IGNORECASE,
    )
    if match:
        text = match.group(1)
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d", "%B %d"):
            try:
                parsed = datetime.strptime(text, fmt)
                year = parsed.year if "%Y" in fmt else today.year
                target = date(year, parsed.month, parsed.day)
                return max(1, (target - today).days)
            except ValueError:
                continue
    return 14


_LOGFIRE_READY = False


def _ensure_logfire() -> None:
    global _LOGFIRE_READY
    if _LOGFIRE_READY:
        return
    import logfire

    logfire.configure(send_to_logfire="if-token-present")
    logfire.instrument_pydantic_ai()
    _LOGFIRE_READY = True


def _default_runner(prompt: str) -> ParseFields:
    from pydantic_ai import Agent

    key = gemini_api_key()
    os.environ.setdefault("GOOGLE_API_KEY", key)
    os.environ.setdefault("GEMINI_API_KEY", key)
    _ensure_logfire()
    agent = Agent("google-gla:gemini-2.5-flash", output_type=ParseFields, system_prompt=PARSE_PROMPT)
    result = agent.run_sync(prompt)
    return result.output


def parse_request(
    raw_text: str,
    requester: Requester,
    known_resource_ids: list[str],
    *,
    runner: Callable[[str], ParseFields] | None = None,
) -> AccessRequest:
    """Turn `raw_text` into an AccessRequest via an injectable structured runner."""
    if runner is None:
        runner = _default_runner
    prompt = (
        f"{PARSE_PROMPT}\nKnown resources: {', '.join(known_resource_ids)}\n{raw_text}"
    )
    fields = runner(prompt)
    resource_ids = constrain_resource_ids(fields.resource_ids, known_resource_ids)
    requested_duration_days = duration_days(raw_text, fields.requested_duration_days)
    return _build_request(
        raw_text,
        requester,
        fields.project,
        resource_ids,
        requested_duration_days,
    )


def _build_request(
    raw_text: str,
    requester: Requester,
    project: str,
    resource_ids: list[str],
    requested_duration_days: int,
) -> AccessRequest:
    return AccessRequest(
        id=str(uuid.uuid4()),
        requester=requester,
        task_description=raw_text,
        project=project,
        resource_ids=resource_ids,
        requested_duration_days=requested_duration_days,
        raw_text=raw_text,
    )
