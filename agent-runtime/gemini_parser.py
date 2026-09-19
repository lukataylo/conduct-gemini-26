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
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

sys.path.append(str(Path(__file__).resolve().parents[1]))

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


def parse_request(raw_text: str, requester: Requester, known_resource_ids: list[str]) -> AccessRequest:
    """Call Gemini with structured output to turn `raw_text` into an AccessRequest.

    NOTE: This is a thin skeleton — wire up the actual `google-genai` client call here.
    Keep the parsing prompt constrained to `known_resource_ids` (pass them in the prompt
    or via an enum-typed schema field) so Gemini can't hallucinate a resource that
    doesn't exist; policy-engine will reject unknown ids anyway, but better to catch it
    here so the requester gets an immediate "did you mean X" style response.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    # TODO(contributor 2): replace with a real google-genai call, e.g.
    #
    #   from google import genai
    #   client = genai.Client(api_key=api_key)
    #   response = client.models.generate_content(
    #       model=MODEL,
    #       contents=[PARSE_PROMPT, f"Known resources: {known_resource_ids}", raw_text],
    #       config={"response_mime_type": "application/json", "response_schema": ...},
    #   )
    #   parsed = json.loads(response.text)
    #
    # then build the AccessRequest below from `parsed` instead of the placeholder.
    raise NotImplementedError("wire up google-genai structured output here")


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
