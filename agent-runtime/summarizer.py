"""
Approver-facing summaries from a typed PolicyDecision.

The model never sees requester raw text — only decision, resource, and identity facts.
"""
from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from envutil import export_gemini_keys  # noqa: E402
from gemini_models import parse_model  # noqa: E402
from shared.schemas import PolicyDecision, Requester, Resource  # noqa: E402

SUMMARY_PROMPT = """Write a short approver-facing summary of this access-policy decision.
Use only the typed facts provided. Do not invent a requester pitch or extra justification.
"""

_LOGFIRE_READY = False


def _ensure_logfire() -> None:
    global _LOGFIRE_READY
    if _LOGFIRE_READY:
        return
    import logfire

    logfire.configure(send_to_logfire="if-token-present")
    logfire.instrument_pydantic_ai()
    _LOGFIRE_READY = True


def _default_runner(prompt: str) -> str:
    from pydantic_ai import Agent

    export_gemini_keys()
    _ensure_logfire()
    agent = Agent(parse_model(), output_type=str, system_prompt=SUMMARY_PROMPT)
    result = agent.run_sync(prompt)
    return result.output


def _build_prompt(decision: PolicyDecision, resource: Resource, requester: Requester) -> str:
    return (
        f"{SUMMARY_PROMPT}"
        f"Decision: {decision.decision.value}\n"
        f"Reason: {decision.reason}\n"
        f"Resource: {resource.name}\n"
        f"Sensitivity: {resource.sensitivity.value}\n"
        f"Owning team: {resource.owning_team}\n"
        f"Requester: {requester.name}\n"
        f"Requester team: {requester.team}\n"
    )


def summarize_decision(
    decision: PolicyDecision,
    resource: Resource,
    requester: Requester,
    *,
    runner: Callable[[str], str] | None = None,
) -> str:
    """Summarize a typed policy decision for an approver."""
    if runner is None:
        runner = _default_runner
    prompt = _build_prompt(decision, resource, requester)
    try:
        text = runner(prompt)
    except Exception:
        return decision.reason
    if not text or not str(text).strip():
        return decision.reason
    return str(text).strip()
