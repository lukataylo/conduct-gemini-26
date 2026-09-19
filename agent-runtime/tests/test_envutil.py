from pathlib import Path

from envutil import gemini_api_key, load_local_env


def test_gemini_api_key_reads_standard_name(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINIAPIKEY", raising=False)
    env = tmp_path / "env.local"
    env.write_text("GEMINI_API_KEY=abc123\n")
    load_local_env(env)
    assert gemini_api_key() == "abc123"


def test_gemini_api_key_accepts_alias(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINIAPIKEY", raising=False)
    env = tmp_path / "env.local"
    env.write_text("GEMINIAPIKEY=alias-key\n")
    load_local_env(env)
    assert gemini_api_key() == "alias-key"


def test_gemini_api_key_missing_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINIAPIKEY", raising=False)
    try:
        gemini_api_key()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "GEMINI_API_KEY" in str(exc)
