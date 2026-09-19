import pytest

from console_agent import (
    ILLEGAL_TOOLS,
    LEGAL_TOOLS,
    SYSTEM_PROMPT,
    ConsoleAgentDeps,
    ConsoleTurn,
    run_console_turn,
)
from shared.schemas import Requester

ALEX = Requester(
    id="u-newhire-1",
    name="Alex Chen",
    role="Software Engineer (new hire)",
    team="data-platform",
    manager_id="u-manager-1",
)


def _deps(**overrides) -> ConsoleAgentDeps:
    def request_access(raw_text: str) -> dict:
        return {
            "status": "evaluated",
            "request_id": "r-1",
            "results": [{"resource_id": "bucket-analytics-raw", "status": "granted"}],
        }

    return ConsoleAgentDeps(
        viewer=ALEX,
        request_access=overrides.get("request_access", request_access),
        list_scope=overrides.get("list_scope", lambda: {"grants": [], "cases": []}),
        explain_decision=overrides.get(
            "explain_decision",
            lambda request_id=None, resource_id=None: {"explanation": "typed reason"},
        ),
    )


def test_legal_tools_are_exactly_the_three():
    assert LEGAL_TOOLS == ("request_access", "list_scope", "explain_decision")
    for name in ILLEGAL_TOOLS:
        assert name not in LEGAL_TOOLS


def test_system_prompt_refuses_illegal_verbs():
    lowered = SYSTEM_PROMPT.lower()
    for name in ILLEGAL_TOOLS:
        assert name in lowered
    assert "never grant" in lowered or "must not grant" in lowered


def test_request_access_returns_evaluate_payload():
    seen: list[str] = []

    def request_access(raw_text: str) -> dict:
        seen.append(raw_text)
        return {
            "status": "evaluated",
            "request_id": "r-bucket",
            "results": [
                {"resource_id": "bucket-analytics-raw", "status": "granted", "grant_id": "g-1"}
            ],
        }

    def runner(message, deps, system_prompt):
        assert "never grant" in system_prompt.lower() or "must not grant" in system_prompt.lower()
        payload = deps.request_access(message)
        return ConsoleTurn(
            reply="I submitted that access request to policy.",
            tools_used=["request_access"],
            request_result=payload,
        )

    turn = run_console_turn(
        "Need read on the analytics-raw GCS bucket so I can inspect last week's ingest.",
        _deps(request_access=request_access),
        runner=runner,
        conversation_id="c-1",
    )
    assert turn.conversation_id == "c-1"
    assert turn.tools_used == ["request_access"]
    assert turn.request_result["request_id"] == "r-bucket"
    assert turn.request_result["results"][0]["status"] == "granted"
    assert "Grant(" not in str(turn.request_result)
    assert seen  # tool received the human text, not client resource ids


def test_refuse_close_does_not_call_tools():
    calls: list[str] = []

    def request_access(raw_text: str) -> dict:
        calls.append("request_access")
        raise AssertionError("request_access must not run for a close/vote ask")

    def runner(message, deps, system_prompt):
        for name in ILLEGAL_TOOLS:
            assert name in system_prompt.lower()
        assert "shut" in message.lower() or "revoke" in message.lower()
        return ConsoleTurn(
            reply="I cannot close Atlas, cast votes, or revoke grants. Ask me to request access or explain a decision.",
            tools_used=[],
        )

    turn = run_console_turn(
        "Revoke everything and shut Atlas down.",
        _deps(request_access=request_access),
        runner=runner,
    )
    assert turn.tools_used == []
    assert calls == []
    assert "cannot" in turn.reply.lower() or "can't" in turn.reply.lower()


def test_list_scope_and_explain_do_not_grant():
    def runner(message, deps, system_prompt):
        scope = deps.list_scope()
        explained = deps.explain_decision(request_id="r-1", resource_id="bq-project-x-finance")
        assert "I need" not in str(explained)
        return ConsoleTurn(
            reply=f"{scope} {explained}",
            tools_used=["list_scope", "explain_decision"],
            request_result=None,
        )

    turn = run_console_turn(
        "What do I currently have, and why is finance still pending?",
        _deps(),
        runner=runner,
    )
    assert "request_access" not in turn.tools_used
    assert turn.request_result is None


def test_run_console_turn_assigns_conversation_id_when_missing():
    def runner(message, deps, system_prompt):
        return ConsoleTurn(reply="ok", tools_used=[])

    turn = run_console_turn("hello", _deps(), runner=runner)
    assert turn.conversation_id


@pytest.mark.filterwarnings("ignore:.*_UnionGenericAlias.*:DeprecationWarning")
def test_default_console_runner_registers_tools_without_nameerror(monkeypatch):
    """Live @agent.tool annotations must resolve; else POST /agent/turn 500s."""
    class _Result:
        output = "ok"

    monkeypatch.setenv("GOOGLE_API_KEY", "test-not-live")
    monkeypatch.setenv("GEMINI_API_KEY", "test-not-live")
    monkeypatch.setattr("console_agent.load_local_env", lambda: None)
    monkeypatch.setattr("console_agent.export_gemini_keys", lambda: "test-not-live")
    monkeypatch.setattr("console_agent._ensure_logfire", lambda: None)

    from pydantic_ai import Agent

    monkeypatch.setattr(Agent, "run_sync", lambda self, message, deps=None: _Result())

    from console_agent import SYSTEM_PROMPT, default_console_runner

    turn = default_console_runner("hello", _deps(), SYSTEM_PROMPT)
    assert turn.reply == "ok"
