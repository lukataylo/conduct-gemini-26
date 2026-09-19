"""Gemini 3.8 Live function declarations + local dispatch into console tools.

The person on the current console tab is who Live acts for: request privileges
and run platform actions for them. Live never writes a Grant or votes.
"""
from __future__ import annotations

import os
from typing import Any

from shared.schemas import Requester

ILLEGAL_LIVE_TOOLS = frozenset({"grant", "vote", "close_project", "patch_policy"})
LEGAL_LIVE_TOOLS = frozenset(
    {
        "request_access",
        "list_scope",
        "explain_decision",
        "request_access_for",
        "enact",
        "confirm_pending",
    }
)

_BLOCKING = "BLOCKING"

LIVE_FUNCTION_DECLARATIONS: list[dict[str, Any]] = [
    {
        "name": "request_access",
        "behavior": _BLOCKING,
        "description": (
            "Request privileges for the person on the current console tab. "
            "If that person is not the signed-in actor, this sponsors them. "
            "Does not grant. Policy decides after the human confirms."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "raw_text": {
                    "type": "STRING",
                    "description": "The human's ask, including resource and duration.",
                }
            },
            "required": ["raw_text"],
        },
    },
    {
        "name": "list_scope",
        "behavior": _BLOCKING,
        "description": (
            "What the tab's person holds, what they have pending, and what is "
            "waiting on the signed-in actor."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "explain_decision",
        "behavior": _BLOCKING,
        "description": "Explain a typed policy decision for a request or resource.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "request_id": {"type": "STRING", "description": "Request id if known."},
                "resource_id": {
                    "type": "STRING",
                    "description": "Resource id such as bucket-analytics-raw.",
                },
            },
        },
    },
    {
        "name": "request_access_for",
        "behavior": _BLOCKING,
        "description": (
            "Sponsor access for a named person who is not the current tab. "
            "Use request_access when the ask is for the tab's person."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "beneficiary_id": {
                    "type": "STRING",
                    "description": "Person id or unique display name.",
                },
                "raw_text": {
                    "type": "STRING",
                    "description": "The access ask in the human's words.",
                },
            },
            "required": ["beneficiary_id", "raw_text"],
        },
    },
    {
        "name": "enact",
        "behavior": _BLOCKING,
        "description": (
            "Do something on a platform for the person on this tab using an "
            "active grant: browse, query, inspect, or export. Never grant or revoke."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "enum": ["browse", "query", "inspect", "export"],
                    "description": "browse | query | inspect | export",
                },
                "raw_text": {
                    "type": "STRING",
                    "description": "What to look at (object, query, BP, export).",
                },
                "resource_id": {
                    "type": "STRING",
                    "description": "Optional seed id if already known.",
                },
            },
            "required": ["action", "raw_text"],
        },
    },
    {
        "name": "confirm_pending",
        "behavior": _BLOCKING,
        "description": (
            "Confirm the pending access request after the human says yes. "
            "Sends it to policy. Does not vote Approve/Deny on cases."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
]


def live_tools_config() -> list[dict[str, Any]]:
    return [{"function_declarations": LIVE_FUNCTION_DECLARATIONS}]


def tab_subject(viewer: Requester, focus: Requester | None) -> Requester:
    """The person on the current console tab — who Live acts for."""
    return focus or viewer


def _strip_secrets(value: Any) -> Any:
    secrets = {
        item
        for item in (
            os.environ.get("GEMINI_API_KEY"),
            os.environ.get("GOOGLE_API_KEY"),
            os.environ.get("GOOGLE_GENAI_API_KEY"),
        )
        if item
    }
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            folded = str(key).lower().replace("-", "_")
            if folded in {"api_key", "apikey", "gemini_api_key", "gemini_key", "google_api_key", "key"} or "api_key" in folded:
                continue
            cleaned[str(key)] = _strip_secrets(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_secrets(item) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret and secret in value:
                value = value.replace(secret, "")
        return value
    return value


def _as_args(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    if isinstance(raw, str):
        import json

        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def execute_live_tool(
    name: str,
    args: Any,
    *,
    viewer: Requester,
    focus: Requester | None,
    conversation_id: str,
) -> dict[str, Any]:
    """Run one Live function call against hub console tools. Never grants."""
    import main

    tool = (name or "").strip()
    payload = _as_args(args)
    if tool in ILLEGAL_LIVE_TOOLS or tool not in LEGAL_LIVE_TOOLS:
        return _strip_secrets({"status": "refused", "tool": tool})

    subject = tab_subject(viewer, focus)

    if tool == "list_scope":
        return _strip_secrets(main._console_list_scope(viewer, focus=subject))

    if tool == "explain_decision":
        return _strip_secrets(
            main._console_explain_decision(
                viewer,
                payload.get("request_id") or None,
                payload.get("resource_id") or None,
            )
        )

    if tool == "request_access":
        raw_text = str(payload.get("raw_text") or "").strip()
        if subject.id != viewer.id:
            result = main._console_request_access_for(
                raw_text,
                viewer,
                subject,
                evaluate=False,
                conversation_id=conversation_id,
            )
        else:
            result = main._console_request_access(
                raw_text,
                viewer,
                evaluate=False,
                conversation_id=conversation_id,
            )
        return _strip_secrets(result)

    if tool == "request_access_for":
        beneficiary = main._resolve_person(str(payload.get("beneficiary_id") or ""))
        if beneficiary is None:
            return {"status": "unknown_person"}
        return _strip_secrets(
            main._console_request_access_for(
                str(payload.get("raw_text") or ""),
                viewer,
                beneficiary,
                evaluate=False,
                conversation_id=conversation_id,
            )
        )

    if tool == "enact":
        return _strip_secrets(
            main._console_enact(
                str(payload.get("action") or ""),
                str(payload.get("raw_text") or ""),
                payload.get("resource_id") or None,
                focus=subject,
                actor=viewer,
            )
        )

    if tool == "confirm_pending":
        return _strip_secrets(main._console_confirm_pending(viewer, conversation_id))

    return {"status": "refused", "tool": tool}
