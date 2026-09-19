"""
Parses a free-text access request into a structured AccessRequest using Gemini's
structured-output mode (response_schema). This is the ONLY place natural language
touches the request pipeline — everything downstream (policy-engine) is typed.
"""
from __future__ import annotations

import re
import sys
import uuid
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

sys.path.append(str(Path(__file__).resolve().parents[1]))

from envutil import export_gemini_keys  # noqa: E402
from gemini_models import parse_model  # noqa: E402
from shared.schemas import AccessRequest, Requester  # noqa: E402

MODEL = DEFAULT_PARSE_MODEL = parse_model()

PARSE_PROMPT = """You are extracting a structured access request from an employee's
(or their coding agent's) free-text message. Identify:
- which resource names/ids they're asking for
- the project this work belongs to
- how many days they need access for (infer a reasonable default like 14 if unstated)
Visible names include: Northwind, 1710001, Customer Master, billing, sales order,
customer directory, export customers, payroll.
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


_HINT_NEEDLES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        (
            ("export all", "sap-customer-directory"),
            ("export customer", "sap-customer-directory"),
            ("customer directory", "sap-customer-directory"),
            ("all customers", "sap-customer-directory"),
            ("payroll", "sap-hr-payroll"),
            ("billing", "sap-billing-display"),
            ("sales order", "sap-sales-order-display"),
            ("northwind", "sap-bp-display"),
            ("1710001", "sap-bp-display"),
            ("customer master", "sap-bp-display"),
            ("business partner", "sap-bp-display"),
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)


def hint_resource_ids(raw_text: str, known: list[str]) -> list[str]:
    """Map utterance keywords to known resource ids. Longer needles first."""
    known_set = set(known)
    lowered = raw_text.lower()
    out: list[str] = []
    for needle, resource_id in _HINT_NEEDLES:
        if resource_id not in known_set or resource_id in out:
            continue
        if needle in lowered:
            out.append(resource_id)
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
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                target = datetime.strptime(text, fmt).date()
                return max(1, (target - today).days)
            except ValueError:
                continue
        for fmt in ("%b %d", "%B %d"):
            try:
                parsed = datetime.strptime(f"{text} {today.year}", f"{fmt} %Y")
                target = date(today.year, parsed.month, parsed.day)
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

    export_gemini_keys()
    _ensure_logfire()
    agent = Agent(parse_model(), output_type=ParseFields, system_prompt=PARSE_PROMPT)
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
    for hinted in hint_resource_ids(raw_text, known_resource_ids):
        if hinted not in resource_ids:
            resource_ids.append(hinted)
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
