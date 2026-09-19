import pytest

from console_agent import (
    ILLEGAL_TOOLS,
    LEGAL_TOOLS,
    SYSTEM_PROMPT,
    ConsoleAgentDeps,
    ConsoleContext,
    ConsoleTurn,
    build_system_prompt,
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

    def request_access_for(beneficiary_id: str, raw_text: str) -> dict:
        return {}

    def enact(action: str, raw_text: str, resource_id: str | None = None) -> dict:
        return {}

    return ConsoleAgentDeps(
        viewer=ALEX,
        request_access=overrides.get("request_access", request_access),
        list_scope=overrides.get("list_scope", lambda: {"grants": [], "cases": []}),
        explain_decision=overrides.get(
            "explain_decision",
            lambda request_id=None, resource_id=None: {"explanation": "typed reason"},
        ),
        request_access_for=overrides.get("request_access_for", request_access_for),
        enact=overrides.get("enact", enact),
    )


def test_legal_tools_include_sponsor_and_enact():
    assert "request_access_for" in LEGAL_TOOLS
    assert "enact" in LEGAL_TOOLS
    for name in ILLEGAL_TOOLS:
        assert name not in LEGAL_TOOLS


def test_system_prompt_still_refuses_illegal_verbs():
    lowered = SYSTEM_PROMPT.lower()
    for name in ILLEGAL_TOOLS:
        assert name in lowered
    assert "never grant" in lowered or "must not grant" in lowered
    assert "assistant" in lowered
    assert "not a person" in lowered or "not priya" in lowered
    built = build_system_prompt(
        ConsoleContext(actor_id="u-manager-1", focus_id="u-finance-owner-1", page="overview", role="manager"),
        actor=Requester(id="u-manager-1", name="Priya Nair", role="Engineering Manager", team="data-platform"),
        focus_name="Jordan Lee",
    ).lower()
    assert "priya nair" in built
    assert "jordan lee" in built
    assert "overview" in built
    assert "request_access_for" in built
    assert "enact" in built
    for name in ILLEGAL_TOOLS:
        assert name in built


def test_request_access_for_and_enact_do_not_write_grants():
    seen: list[tuple] = []

    def request_access_for(beneficiary_id: str, raw_text: str) -> dict:
        seen.append(("sponsor", beneficiary_id, raw_text))
        return {"status": "needs_confirmation", "preview": {"beneficiary_id": beneficiary_id}}

    def enact(action: str, raw_text: str, resource_id: str | None = None) -> dict:
        seen.append(("enact", action, raw_text, resource_id))
        return {"status": "enqueued", "action": action}

    def runner(message, deps, system_prompt):
        assert "priya" in system_prompt.lower()
        if "grant jordan" in message.lower():
            payload = deps.request_access_for("u-finance-owner-1", message)
            return ConsoleTurn(reply="Confirm sponsoring Jordan.", tools_used=["request_access_for"], request_result=payload)
        payload = deps.enact("query", message, "bq-project-x-finance")
        return ConsoleTurn(reply="Looking at finance.", tools_used=["enact"], enact_result=payload)

    deps = _deps(request_access_for=request_access_for, enact=enact)
    deps.context = ConsoleContext(actor_id="u-manager-1", focus_id="u-finance-owner-1", page="timeline", role="manager")
    deps.focus = Requester(id="u-finance-owner-1", name="Jordan Lee", role="Finance Data Owner", team="finance")
    deps.viewer = Requester(id="u-manager-1", name="Priya Nair", role="Engineering Manager", team="data-platform")

    turn = run_console_turn("grant Jordan read on analytics-raw for Atlas", deps, runner=runner)
    assert turn.tools_used == ["request_access_for"]
    assert seen[0][0] == "sponsor"
    assert "Grant(" not in str(turn.request_result)

    turn2 = run_console_turn("invoice lines in finance", deps, runner=runner)
    assert turn2.tools_used == ["enact"]
    assert turn2.enact_result["status"] == "enqueued"


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


@pytest.mark.filterwarnings("ignore:.*_UnionGenericAlias.*:DeprecationWarning")
def test_history_is_prepended_to_model_message_not_tools(monkeypatch):
    captured: dict = {}

    class _Result:
        output = "ok"

    def run_sync(self, message, deps=None):
        captured["message"] = message
        return _Result()

    monkeypatch.setenv("GOOGLE_API_KEY", "test-not-live")
    monkeypatch.setenv("GEMINI_API_KEY", "test-not-live")
    monkeypatch.setattr("console_agent.load_local_env", lambda: None)
    monkeypatch.setattr("console_agent.export_gemini_keys", lambda: "test-not-live")
    monkeypatch.setattr("console_agent._ensure_logfire", lambda: None)

    from pydantic_ai import Agent

    monkeypatch.setattr(Agent, "run_sync", run_sync)

    from console_agent import SYSTEM_PROMPT, default_console_runner

    deps = _deps()
    deps.history = [{"role": "user", "content": f"old-{i}"} for i in range(25)]
    turn = default_console_runner("latest ask", deps, SYSTEM_PROMPT)
    assert turn.reply == "ok"
    model_message = captured["message"]
    assert model_message.endswith("latest ask")
    assert "old-0" not in model_message
    assert "old-5" in model_message
    assert "old-24" in model_message
