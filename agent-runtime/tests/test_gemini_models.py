from gemini_models import computer_use_model, computer_use_thinking, live_model, parse_model


def test_defaults_are_lite_cu_and_3_8_parse(monkeypatch):
    monkeypatch.delenv("GEMINI_PARSE_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_CU_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_CU_THINKING", raising=False)
    assert parse_model() == "google:gemini-3.8-flash"
    assert computer_use_model() == "gemini-3.5-flash-lite"
    assert computer_use_thinking() == "minimal"


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("GEMINI_PARSE_MODEL", "google:gemini-3.5-flash")
    monkeypatch.setenv("GEMINI_CU_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setenv("GEMINI_CU_THINKING", "medium")
    assert parse_model() == "google:gemini-3.5-flash"
    assert computer_use_model() == "gemini-3.5-flash-lite"
    assert computer_use_thinking() == "medium"


def test_live_model_defaults_to_3_8_live_and_honors_env(monkeypatch):
    monkeypatch.delenv("GEMINI_LIVE_MODEL", raising=False)
    assert live_model() == "gemini-3.8-live"
    monkeypatch.setenv("GEMINI_LIVE_MODEL", "gemini-live-override")
    assert live_model() == "gemini-live-override"
