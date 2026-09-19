"""Console agent: talk to the human aperture. Never grants — tools request or explain."""
from __future__ import annotations

import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

sys.path.append(str(Path(__file__).resolve().parents[1]))

from envutil import export_gemini_keys  # noqa: E402
from gemini_models import parse_model  # noqa: E402
from shared.schemas import Requester  # noqa: E402

LEGAL_TOOLS = ("request_access", "list_scope", "explain_decision")
ILLEGAL_TOOLS = ("grant", "vote", "close_project", "patch_policy")

SYSTEM_PROMPT = """You are the Aperture console agent for one human viewer.

You never grant access. You never write a Grant. Policy-engine decides.
You may only use these tools: request_access, list_scope, explain_decision.

Illegal — refuse, do not call any tool, do not claim you did it:
- grant
- vote (Approve / Deny)
- close_project (including "shut Atlas down" or revoke everything)
- patch_policy

If the human asks for access, call request_access with their raw_text.
If they ask what they have or what is pending, call list_scope.
If they ask why a decision happened, call explain_decision with a request_id or resource_id.
Do not invent resource ids. Do not POST votes. Do not close projects.
"""


@dataclass
class ConsoleAgentDeps:
    viewer: Requester
    request_access: Callable[[str], dict]
    list_scope: Callable[[], dict]
    explain_decision: Callable[[str | None, str | None], dict]


class ConsoleTurn(BaseModel):
    reply: str
    tools_used: list[str] = Field(default_factory=list)
    request_result: dict | None = None
    conversation_id: str = ""


ConsoleRunner = Callable[[str, ConsoleAgentDeps, str], ConsoleTurn]

_LOGFIRE_READY = False


def _ensure_logfire() -> None:
    global _LOGFIRE_READY
    if _LOGFIRE_READY:
        return
    import logfire

    logfire.configure(send_to_logfire="if-token-present")
    logfire.instrument_pydantic_ai()
    _LOGFIRE_READY = True


def default_console_runner(message: str, deps: ConsoleAgentDeps, system_prompt: str) -> ConsoleTurn:
    """Live Gemini path. Unit tests inject `runner` and never call this."""
    from pydantic_ai import Agent, RunContext

    export_gemini_keys()
    _ensure_logfire()
    used: list[str] = []
    last_request: dict | None = None
    agent = Agent(parse_model(), deps_type=ConsoleAgentDeps, system_prompt=system_prompt)

    @agent.tool
    def request_access(ctx: RunContext[ConsoleAgentDeps], raw_text: str) -> dict:
        nonlocal last_request
        used.append("request_access")
        last_request = ctx.deps.request_access(raw_text)
        return last_request

    @agent.tool
    def list_scope(ctx: RunContext[ConsoleAgentDeps]) -> dict:
        used.append("list_scope")
        return ctx.deps.list_scope()

    @agent.tool
    def explain_decision(
        ctx: RunContext[ConsoleAgentDeps],
        request_id: str | None = None,
        resource_id: str | None = None,
    ) -> dict:
        used.append("explain_decision")
        return ctx.deps.explain_decision(request_id, resource_id)

    result = agent.run_sync(message, deps=deps)
    return ConsoleTurn(reply=str(result.output), tools_used=used, request_result=last_request)


def run_console_turn(
    message: str,
    deps: ConsoleAgentDeps,
    *,
    runner: ConsoleRunner | None = None,
    conversation_id: str | None = None,
) -> ConsoleTurn:
    run = runner or default_console_runner
    turn = run(message, deps, SYSTEM_PROMPT)
    cid = conversation_id or turn.conversation_id or str(uuid.uuid4())
    if turn.conversation_id == cid:
        return turn
    return turn.model_copy(update={"conversation_id": cid})
