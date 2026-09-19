"""Drop-in POST /agent/live/session. Mount later with mount_live_session(app)."""
from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

LIVE_SESSION_IMPL: Callable[..., dict] | None = None

router = APIRouter()

_SECRET_FIELD_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "gemini_api_key",
        "gemini_key",
        "google_api_key",
        "key",
    }
)


class LiveSessionIn(BaseModel):
    viewer_id: str
    focus_id: str | None = None
    page: str = "overview"
    conversation_id: str | None = None


class LiveSessionOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ok: bool
    conversation_id: str
    model: str | None = None
    fallback: str | None = None


def _agent_runtime_on_path() -> None:
    runtime = str(Path(__file__).resolve().parents[1] / "agent-runtime")
    if runtime not in sys.path:
        sys.path.append(runtime)


def _known_requesters() -> dict:
    import main

    return main.KNOWN_REQUESTERS


def _viewer_console_role(viewer: Any) -> str:
    if re.search(r"manager|owner|lead|head", getattr(viewer, "role", None) or "", re.I):
        return "manager"
    return "user"


def _normalize_focus(focus_id: str | None) -> str | None:
    if focus_id is None:
        return None
    key = focus_id.strip()
    if not key or key.lower() in {"all", "everyone"}:
        return None
    return key


def _env_secrets() -> set[str]:
    return {
        value
        for value in (
            os.environ.get("GEMINI_API_KEY"),
            os.environ.get("GOOGLE_API_KEY"),
            os.environ.get("GOOGLE_GENAI_API_KEY"),
        )
        if value
    }


def _is_secret_field(name: str) -> bool:
    folded = name.lower().replace("-", "_")
    return folded in _SECRET_FIELD_NAMES or "api_key" in folded


def _strip_secrets(value: Any, secrets: set[str]) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _is_secret_field(str(key)):
                continue
            cleaned[key] = _strip_secrets(item, secrets)
        return cleaned
    if isinstance(value, list):
        return [_strip_secrets(item, secrets) for item in value]
    if isinstance(value, str) and secrets:
        for secret in secrets:
            if secret and secret in value:
                value = value.replace(secret, "")
        return value
    return value


def _as_dict(result: Any) -> dict:
    if isinstance(result, dict):
        return dict(result)
    if hasattr(result, "model_dump"):
        return dict(result.model_dump())
    raise TypeError("live session impl must return a dict")


def _start(context: dict, conversation_id: str) -> dict:
    if LIVE_SESSION_IMPL is not None:
        result = LIVE_SESSION_IMPL(context, conversation_id)
    else:
        _agent_runtime_on_path()
        from live_session import start_live_session

        result = start_live_session(context, conversation_id)
    payload = _strip_secrets(_as_dict(result), _env_secrets())
    payload["conversation_id"] = conversation_id
    return payload


@router.post("/agent/live/session")
def create_live_session(body: LiveSessionIn) -> LiveSessionOut:
    viewer = _known_requesters().get(body.viewer_id)
    if viewer is None:
        raise HTTPException(400, f"unknown requester '{body.viewer_id}'")
    conversation_id = (body.conversation_id or "").strip() or str(uuid.uuid4())
    context = {
        "actor_id": viewer.id,
        "focus_id": _normalize_focus(body.focus_id),
        "page": body.page or "overview",
        "role": _viewer_console_role(viewer),
    }
    payload = _start(context, conversation_id)
    return LiveSessionOut(
        ok=bool(payload.get("ok", False)),
        conversation_id=conversation_id,
        model=payload.get("model"),
        fallback=payload.get("fallback"),
    )


def mount_live_session(app: FastAPI) -> None:
    from live_ws import mount_live_ws

    app.include_router(router)
    mount_live_ws(app)
