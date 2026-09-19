"""
Parses a free-text access request into a structured AccessRequest using Gemini's
structured-output mode (response_schema). This is the ONLY place natural language
touches the request pipeline — everything downstream (policy-engine) is typed.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

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
