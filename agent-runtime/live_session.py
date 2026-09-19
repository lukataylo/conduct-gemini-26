"""Pin a Gemini Live session. Offline handshake only — no WebRTC."""
from __future__ import annotations

import os
from typing import Any

from gemini_models import live_model

LIVE_ASSISTANT_INSTRUCTION = (
    "You are the Aperture assistant agent, not any named person. "
    "You are a natural two-way spoken helper. "
    "Never grant, vote, close_project, or patch_policy."
)


def live_instruction(context: dict | None) -> str:
    """Spoken-session system text. Never includes API keys."""
    parts = [LIVE_ASSISTANT_INSTRUCTION]
    ctx = context or {}
    actor = ctx.get("actor_name") or ctx.get("actor_id") or ctx.get("name")
    if actor:
        parts.append(f"You are helping {actor}, not speaking as them.")
    focus = ctx.get("focus_name") or ctx.get("focus") or ctx.get("focus_id")
    if focus:
        parts.append(f"You are looking at {focus}.")
    text = " ".join(parts)
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        text = text.replace(key, "")
    return text


def start_live_session(context: Any, conversation_id: str) -> dict:
    """Return session metadata. Never include GEMINI_API_KEY in the dict."""
    del context  # reserved for a later Live host; unused in this pin
    model = live_model()
    if not os.environ.get("GEMINI_API_KEY"):
        return {
            "ok": False,
            "conversation_id": conversation_id,
            "model": model,
            "fallback": "text",
        }
    return {
        "ok": True,
        "conversation_id": conversation_id,
        "model": model,
        "fallback": None,
    }
