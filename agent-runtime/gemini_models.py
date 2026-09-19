"""Pinned Gemini model ids. AI Studio only — not Vertex.

Computer Use loop is aligned with google-gemini/computer-use-preview (agent.py):
query-first, FunctionResponse screenshots, prune after 3 turns.

Models (official preview README + CU docs):
- gemini-3.5-flash-lite: low-latency CU (default — vision turns dominate wall time)
- gemini-3.8-flash: current CU-recommended quality
- gemini-3.6-flash: computer-use-preview main.py default
- gemini-2.5-computer-use-preview-10-2025: legacy, do not use

Pydantic AI v2 provider prefix is ``google:`` (``google-gla:`` was removed).
"""
from __future__ import annotations

import os

DEFAULT_PARSE_MODEL = "google:gemini-3.8-flash"
DEFAULT_CU_MODEL = "gemini-3.5-flash-lite"
DEFAULT_LIVE_MODEL = "gemini-2.5-flash-native-audio"
# 3.8 Flash supports low/medium/high (``minimal`` errors). Lite supports
# ``minimal``. Official loop uses include_thoughts; we skip thoughts.
DEFAULT_CU_THINKING = "low"


def parse_model() -> str:
    return os.environ.get("GEMINI_PARSE_MODEL") or DEFAULT_PARSE_MODEL


def computer_use_model() -> str:
    return os.environ.get("GEMINI_CU_MODEL") or DEFAULT_CU_MODEL


def computer_use_thinking() -> str:
    override = os.environ.get("GEMINI_CU_THINKING")
    if override:
        return override
    if "lite" in computer_use_model():
        return "minimal"
    return DEFAULT_CU_THINKING


def live_model() -> str:
    return os.environ.get("GEMINI_LIVE_MODEL") or DEFAULT_LIVE_MODEL
