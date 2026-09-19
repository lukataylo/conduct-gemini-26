"""Pin a Gemini Live session. Offline handshake only — no WebRTC."""
from __future__ import annotations

import os
from typing import Any

from gemini_models import live_model


def start_live_session(context: Any, conversation_id: str) -> dict:
    """Return session metadata. Never include GEMINI_API_KEY in the dict."""
    del context  # reserved for a later Live host; unused in this pin
    model = live_model()
    if not os.environ.get("GEMINI_API_KEY"):
        return {
            "ok": False,
            "conversation_id": conversation_id,
            "model": model,
            "fallback": "speech",
        }
    return {
        "ok": True,
        "conversation_id": conversation_id,
        "model": model,
        "fallback": None,
    }
