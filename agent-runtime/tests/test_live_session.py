from gemini_models import DEFAULT_LIVE_MODEL, live_model
from live_session import LIVE_ASSISTANT_INSTRUCTION, live_instruction, start_live_session

SECRET = "sk-test-live-key-must-not-leak"


def test_live_model_default_and_env(monkeypatch):
    monkeypatch.delenv("GEMINI_LIVE_MODEL", raising=False)
    assert DEFAULT_LIVE_MODEL == "gemini-3.8-live"
    assert live_model() == DEFAULT_LIVE_MODEL
    monkeypatch.setenv("GEMINI_LIVE_MODEL", "gemini-live-override")
    assert live_model() == "gemini-live-override"


def test_start_live_session_without_key_falls_back_to_text(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_LIVE_MODEL", raising=False)
    result = start_live_session({"actor_id": "u-manager-1"}, "conv-text")
    assert result == {
        "ok": False,
        "conversation_id": "conv-text",
        "model": DEFAULT_LIVE_MODEL,
        "fallback": "text",
    }
    assert SECRET not in str(result)
    assert "GEMINI_API_KEY" not in result
    assert "api_key" not in result


def test_start_live_session_with_key_never_returns_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    monkeypatch.delenv("GEMINI_LIVE_MODEL", raising=False)
    result = start_live_session({"actor_id": "u-manager-1"}, "conv-live")
    assert result == {
        "ok": True,
        "conversation_id": "conv-live",
        "model": DEFAULT_LIVE_MODEL,
        "fallback": None,
    }
    assert SECRET not in result
    assert SECRET not in str(result)
    assert SECRET not in result.values()
    assert "GEMINI_API_KEY" not in result
    assert "api_key" not in result


def test_live_instruction_helps_actor_and_focus(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    text = live_instruction(
        {
            "actor_name": "Priya Nair",
            "actor_id": "u-manager-1",
            "focus": "Jordan Lee",
        }
    )
    assert LIVE_ASSISTANT_INSTRUCTION in text
    assert "helping Priya Nair" in text
    assert "not speaking as them" in text
    assert "looking at Jordan Lee" in text
    assert "current console tab is Jordan Lee" in text
    assert "request_access" in text
    assert "list_scope" in text
    assert SECRET not in text
    assert "GEMINI_API_KEY" not in text
