from gemini_models import computer_use_model, computer_use_thinking, parse_model


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
