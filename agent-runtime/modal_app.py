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
from a2ui import compose_ui
from audit_logger import set_emitter
from computer_use import current_sandbox_id, execute_grant
from gemini_parser import parse_request
from http_emitter import make_emitter
from mcp_server import tools_for_grants
from shared.schemas import EscalationCase, Grant, Requester

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
    event = execute(
        grant,
        console_url,
        watch_url=watch_url,
        callback_base_url=callback_base_url,
    )
    return {
        "sandbox_id": current_sandbox_id(),
        "watch_url": watch_url,
        "grant_id": grant.id,
        "event": event.model_dump(mode="json"),
    }


def handle_compose(payload: dict, *, compose=compose_ui) -> dict:
    """Turn a Modal compose payload into UISpec JSON."""
    try:
        grants_data = payload["grants"]
        cases_data = payload["cases"]
        role = payload["role"]
        viewer_id = payload["viewer_id"]
    except KeyError as exc:
        raise ValueError(f"missing field: {exc.args[0]}") from exc
    grants = [
        g if isinstance(g, Grant) else Grant.model_validate(g) for g in grants_data
    ]
    cases = [
        c if isinstance(c, EscalationCase) else EscalationCase.model_validate(c)
        for c in cases_data
    ]
    watch_urls = payload.get("watch_urls") or None
    kwargs: dict = {"viewer_id": viewer_id}
    if watch_urls:
        kwargs["watch_urls"] = watch_urls
    spec = compose(grants, cases, role, **kwargs)
    return spec.model_dump(mode="json")


def handle_mcp_tools(payload: dict) -> dict:
    grants_data = payload.get("grants") or []
    grants = [
        g if isinstance(g, Grant) else Grant.model_validate(g) for g in grants_data
    ]
    return {"tools": tools_for_grants(grants)}


def handle_watch() -> dict:
    return {"sandbox_id": current_sandbox_id(), "ready": True}


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


@app.function(image=image, secrets=secrets)
@modal.fastapi_endpoint(method="POST")
def compose_ui_endpoint(payload: dict) -> dict:
    """POST { grants, cases, role, viewer_id } -> UISpec (as dict)."""
    return handle_compose(payload)


@app.function(image=image, secrets=secrets)
@modal.fastapi_endpoint(method="POST")
def mcp_tools_endpoint(payload: dict) -> dict:
    """POST { grants } -> scoped MCP tool list for active grants only."""
    return handle_mcp_tools(payload)


@app.function(image=image)
@modal.fastapi_endpoint(method="GET")
def watch_endpoint() -> dict:
    """Lightweight watch probe for ConsoleWatchCard / AGENT_RUNTIME_WATCH_URL."""
    return handle_watch()
