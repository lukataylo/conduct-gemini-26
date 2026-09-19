from gemini_models import DEFAULT_LIVE_MODEL, live_model
from live_session import start_live_session

SECRET = "sk-test-live-key-must-not-leak"


def test_live_model_default_and_env(monkeypatch):
    monkeypatch.delenv("GEMINI_LIVE_MODEL", raising=False)
    assert DEFAULT_LIVE_MODEL == "gemini-2.5-flash-native-audio"
    assert live_model() == DEFAULT_LIVE_MODEL
    monkeypatch.setenv("GEMINI_LIVE_MODEL", "gemini-live-override")
    assert live_model() == "gemini-live-override"


def test_start_live_session_without_key_falls_back_to_speech(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_LIVE_MODEL", raising=False)
    result = start_live_session({"actor_id": "u-manager-1"}, "conv-speech")
    assert result == {
        "ok": False,
        "conversation_id": "conv-speech",
        "model": DEFAULT_LIVE_MODEL,
        "fallback": "speech",
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
