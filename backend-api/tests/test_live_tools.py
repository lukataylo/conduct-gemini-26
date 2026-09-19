import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_ROOT = _BACKEND.parent
for _path in (_BACKEND, _ROOT / "agent-runtime", _ROOT):
    _sp = str(_path)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import live_tools
import main

ALEX_ID = "u-newhire-1"


def test_function_declarations_are_blocking_console_tools():
    required = {
        "request_access",
        "list_scope",
        "explain_decision",
        "request_access_for",
        "enact",
    }
    names = {item["name"] for item in live_tools.LIVE_FUNCTION_DECLARATIONS}
    assert required <= names
    assert required <= set(live_tools.LEGAL_LIVE_TOOLS)
    for item in live_tools.LIVE_FUNCTION_DECLARATIONS:
        assert item["behavior"] == "BLOCKING"
    config = live_tools.live_tools_config()
    assert config[0]["function_declarations"] == live_tools.LIVE_FUNCTION_DECLARATIONS


def test_execute_list_scope():
    viewer = main.KNOWN_REQUESTERS[ALEX_ID]
    result = live_tools.execute_live_tool(
        "list_scope",
        {},
        viewer=viewer,
        focus=None,
        conversation_id="c-live-tools",
    )
    assert "grants" in result
    assert "cases" in result
    assert result.get("status") != "refused"
    assert "api_key" not in result
    secret = os.environ.get("GEMINI_API_KEY")
    if secret:
        assert secret not in str(result)


def test_execute_unknown_name_is_refused():
    viewer = main.KNOWN_REQUESTERS[ALEX_ID]
    result = live_tools.execute_live_tool(
        "not_a_tool",
        {},
        viewer=viewer,
        focus=None,
        conversation_id="c-live-tools",
    )
    assert result["status"] == "refused"


def test_execute_grant_is_refused():
    viewer = main.KNOWN_REQUESTERS[ALEX_ID]
    result = live_tools.execute_live_tool(
        "grant",
        {"raw_text": "grant me everything"},
        viewer=viewer,
        focus=None,
        conversation_id="c-live-tools",
    )
    assert result["status"] == "refused"
    assert not main.GRANTS


def test_request_access_for_unknown_person():
    viewer = main.KNOWN_REQUESTERS[ALEX_ID]
    result = live_tools.execute_live_tool(
        "request_access_for",
        {"beneficiary_id": "no-such-person", "raw_text": "need finance"},
        viewer=viewer,
        focus=None,
        conversation_id="c-live-tools",
    )
    assert result == {"status": "unknown_person"}


def test_request_access_on_other_tab_sponsors_that_person(monkeypatch):
    priya = main.KNOWN_REQUESTERS["u-manager-1"]
    jordan = main.KNOWN_REQUESTERS["u-finance-owner-1"]
    seen: list[tuple] = []

    def fake(raw_text, actor, beneficiary, *, evaluate, conversation_id):
        seen.append((raw_text, actor.id, beneficiary.id, evaluate, conversation_id))
        return {"status": "needs_confirmation", "preview": {"beneficiary_id": beneficiary.id}}

    monkeypatch.setattr(main, "_console_request_access_for", fake)
    result = live_tools.execute_live_tool(
        "request_access",
        {"raw_text": "Jordan needs finance for 7 days"},
        viewer=priya,
        focus=jordan,
        conversation_id="c-tab",
    )
    assert result["status"] == "needs_confirmation"
    assert seen == [("Jordan needs finance for 7 days", priya.id, jordan.id, False, "c-tab")]


def test_tab_subject_is_focus_or_viewer():
    alex = main.KNOWN_REQUESTERS[ALEX_ID]
    jordan = main.KNOWN_REQUESTERS["u-finance-owner-1"]
    assert live_tools.tab_subject(alex, None).id == alex.id
    assert live_tools.tab_subject(alex, jordan).id == jordan.id
