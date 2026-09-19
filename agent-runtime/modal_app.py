"""
Modal deployment for agent-runtime: exposes request-parsing and grant-execution as
serverless functions/endpoints backend-api can call, so the (potentially slow/computer-
use-heavy) agent work doesn't block backend-api's request/response cycle.

Run locally:   modal serve agent-runtime/modal_app.py
Deploy:        modal deploy agent-runtime/modal_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parents[1]))

import modal
from audit_logger import set_emitter
from computer_use import execute_grant
from gemini_parser import parse_request
from http_emitter import make_emitter
from shared.schemas import Grant, Requester

app = modal.App("access-scope-agent-runtime")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "pydantic>=2.6",
        "pydantic-ai",
        "logfire",
        "google-genai",
        "playwright",
        "httpx",
        "fastapi",
    )
    .run_commands("playwright install chromium")
    .add_local_dir("../shared", remote_path="/root/shared")
    .add_local_dir(".", remote_path="/root/agent-runtime")
)

secrets = [modal.Secret.from_name("access-scope-agent-secrets")]  # GEMINI_API_KEY, LOGFIRE_TOKEN


def handle_parse(payload: dict, *, parse=parse_request) -> dict:
    """Turn a Modal parse payload into AccessRequest JSON."""
    try:
        raw_text = payload["raw_text"]
        requester_data = payload["requester"]
        known = payload["known_resource_ids"]
    except KeyError as exc:
        raise ValueError(f"missing field: {exc.args[0]}") from exc
    requester = (
        requester_data
        if isinstance(requester_data, Requester)
        else Requester.model_validate(requester_data)
    )
    request = parse(raw_text, requester, known)
    return request.model_dump(mode="json")


def handle_execute(payload: dict, *, execute=execute_grant) -> dict:
    """Run execute_grant and return the Modal execute payload."""
    try:
        grant_data = payload["grant"]
        console_url = payload["console_url"]
    except KeyError as exc:
        raise ValueError(f"missing field: {exc.args[0]}") from exc
    grant = grant_data if isinstance(grant_data, Grant) else Grant.model_validate(grant_data)
    callback_base_url = payload.get("callback_base_url")
    watch_url = payload.get("watch_url")
    if callback_base_url:
        set_emitter(make_emitter(callback_base_url))
    event = execute(grant, console_url, watch_url=watch_url)
    return {
        "sandbox_id": "local",
        "watch_url": watch_url,
        "grant_id": grant.id,
        "event": event.model_dump(mode="json"),
    }


@app.function(image=image, secrets=secrets)
@modal.fastapi_endpoint(method="POST")
def parse_request_endpoint(payload: dict) -> dict:
    """POST { raw_text, requester, known_resource_ids } -> AccessRequest (as dict)."""
    return handle_parse(payload)


@app.function(image=image, secrets=secrets, timeout=600)
@modal.fastapi_endpoint(method="POST")
def execute_grant_endpoint(payload: dict) -> dict:
    """POST { grant, console_url, callback_base_url? } -> execute result."""
    return handle_execute(payload)
