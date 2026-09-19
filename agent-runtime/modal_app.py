"""
Modal deployment for agent-runtime: exposes request-parsing and grant-execution as
serverless functions/endpoints backend-api can call, so the (potentially slow/computer-
use-heavy) agent work doesn't block backend-api's request/response cycle.

Run locally:   modal serve agent-runtime/modal_app.py
Deploy:        modal deploy agent-runtime/modal_app.py
"""
from __future__ import annotations

import modal

app = modal.App("access-scope-agent-runtime")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "pydantic>=2.6",
        "google-genai",
        "anthropic",
        "fastapi",
    )
    .add_local_dir("../shared", remote_path="/root/shared")
    .add_local_dir(".", remote_path="/root/agent-runtime")
)

secrets = [modal.Secret.from_name("access-scope-agent-secrets")]  # GEMINI_API_KEY, ANTHROPIC_API_KEY


@app.function(image=image, secrets=secrets)
@modal.fastapi_endpoint(method="POST")
def parse_request_endpoint(payload: dict) -> dict:
    """POST { raw_text, requester, known_resource_ids } -> AccessRequest (as dict).

    TODO(contributor 2): import gemini_parser.parse_request and call it here once the
    real Gemini client call is wired up.
    """
    raise NotImplementedError("wire up gemini_parser.parse_request")


@app.function(image=image, secrets=secrets, timeout=600)
@modal.fastapi_endpoint(method="POST")
def execute_grant_endpoint(payload: dict) -> dict:
    """POST { grant, console_url } -> AuditEvent (as dict).

    TODO(contributor 2): import computer_use.execute_grant and call it here once the
    computer-use loop is wired up. This is likely to run long (real UI interaction) —
    consider making this a Modal function with a webhook callback to backend-api instead
    of a synchronous request/response, if it's too slow for the demo.
    """
    raise NotImplementedError("wire up computer_use.execute_grant")
