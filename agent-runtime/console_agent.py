"""Console agent: talk to the human aperture. Never grants — tools request or explain."""
from __future__ import annotations

import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

sys.path.append(str(Path(__file__).resolve().parents[1]))

from envutil import export_gemini_keys, load_local_env  # noqa: E402
from gemini_models import parse_model  # noqa: E402
from pydantic_ai import RunContext  # noqa: E402
from shared.schemas import Requester  # noqa: E402

LEGAL_TOOLS = ("request_access", "list_scope", "explain_decision", "request_access_for", "enact")
ILLEGAL_TOOLS = ("grant", "vote", "close_project", "patch_policy")

SYSTEM_PROMPT = """You are the Aperture console agent for one human viewer.

You never grant access. You never write a Grant. Policy-engine decides.
You may only use these tools: request_access, list_scope, explain_decision, request_access_for, enact.

Illegal — refuse, do not call any tool, do not claim you did it:
- grant
- vote (Approve / Deny)
- close_project (including "shut Atlas down" or revoke everything)
- patch_policy

Never enact grant or revoke. enact is only browse, query, inspect, or export on an existing grant.

If the human asks for access for themselves, call request_access with their raw_text.
If they ask to sponsor access for someone else, call request_access_for with beneficiary_id and raw_text.
If they ask to look at, query, inspect, or export a resource they already hold, call enact.
If they ask what they have or what is pending, call list_scope.
If they ask why a decision happened, call explain_decision with a request_id or resource_id.
Do not invent resource ids. Do not POST votes. Do not close projects.
"""


class ConsoleContext(BaseModel):
    actor_id: str
    focus_id: str | None = None
    page: str = "overview"
    role: str = "user"


def build_system_prompt(
    ctx: ConsoleContext | None,
    actor: Requester | None = None,
    focus_name: str | None = None,
) -> str:
    if ctx is None:
        return SYSTEM_PROMPT
    actor_name = actor.name if actor is not None else ctx.actor_id
    focus = focus_name or "everyone"
    return (
        f"{SYSTEM_PROMPT.rstrip()}\n"
        f"\nYou are talking to {actor_name}."
        f"\nFocus is {focus}."
        f"\nCurrent page: {ctx.page}."
        f"\nConsole role: {ctx.role}."
    )


def _history_prefix(history: list[dict] | None) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for item in history[-20:]:
        role = item.get("role", "")
        text = item.get("content") or item.get("text") or item.get("message") or ""
        if not text:
            continue
        lines.append(f"{role}: {text}" if role else str(text))
    return "\n".join(lines)


@dataclass
class ConsoleAgentDeps:
    viewer: Requester
    request_access: Callable[[str], dict]
    list_scope: Callable[[], dict]
    explain_decision: Callable[[str | None, str | None], dict]
    request_access_for: Callable[[str, str], dict] | None = None
    enact: Callable[[str, str, str | None], dict] | None = None
    context: ConsoleContext | None = None
    history: list[dict] = field(default_factory=list)
    focus: Requester | None = None


class ConsoleTurn(BaseModel):
    reply: str
    tools_used: list[str] = Field(default_factory=list)
    request_result: dict | None = None
    enact_result: dict | None = None
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
    from pydantic_ai import Agent

    load_local_env()
    export_gemini_keys()
    _ensure_logfire()
    used: list[str] = []
    last_request: dict | None = None
    last_enact: dict | None = None
    if deps.context is not None:
        system_prompt = build_system_prompt(
            deps.context,
            deps.viewer,
            deps.focus.name if deps.focus else None,
        )
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

    @agent.tool
    def request_access_for(ctx: RunContext[ConsoleAgentDeps], beneficiary_id: str, raw_text: str) -> dict:
        nonlocal last_request
        used.append("request_access_for")
        fn = ctx.deps.request_access_for
        last_request = fn(beneficiary_id, raw_text) if fn else {}
        return last_request

    @agent.tool
    def enact(
        ctx: RunContext[ConsoleAgentDeps],
        action: str,
        raw_text: str,
        resource_id: str | None = None,
    ) -> dict:
        nonlocal last_enact
        used.append("enact")
        fn = ctx.deps.enact
        last_enact = fn(action, raw_text, resource_id) if fn else {}
        return last_enact

    prefix = _history_prefix(deps.history)
    model_message = f"{prefix}\n{message}" if prefix else message
    result = agent.run_sync(model_message, deps=deps)
    return ConsoleTurn(
        reply=str(result.output),
        tools_used=used,
        request_result=last_request,
        enact_result=last_enact,
    )


def run_console_turn(
    message: str,
    deps: ConsoleAgentDeps,
    *,
    runner: ConsoleRunner | None = None,
    conversation_id: str | None = None,
) -> ConsoleTurn:
    run = runner or default_console_runner
    prompt = build_system_prompt(
        deps.context,
        deps.viewer,
        deps.focus.name if deps.focus else None,
    )
    turn = run(message, deps, prompt)
    cid = conversation_id or turn.conversation_id or str(uuid.uuid4())
    if turn.conversation_id == cid:
        return turn
    return turn.model_copy(update={"conversation_id": cid})
