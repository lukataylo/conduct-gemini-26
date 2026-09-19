from pathlib import Path

import pytest
from computer_use import (
    GEMINI_CU_MODEL,
    MAX_RECENT_TURN_WITH_SCREENSHOTS,
    _apply_page_action,
    _denorm_coord,
    _normalize_cu_action,
    browse_goal,
    completed_event,
    enact_goal,
    execute_grant,
    grant_goal,
    host_allowed,
    prune_old_screenshots,
    query_goal,
    revoke_goal,
    run_computer_use_loop,
    verify_active,
    verify_inactive,
)
from gemini_models import DEFAULT_CU_MODEL, DEFAULT_PARSE_MODEL
from mock_console.server import serve_in_thread


def _serve_console():
    server = serve_in_thread(port=0)
    host, port = server.server_address
    return server, f"http://{host}:{port}/"


def test_models_are_lite_cu_and_3_8_parse():
    assert DEFAULT_CU_MODEL == "gemini-3.5-flash-lite"
    assert GEMINI_CU_MODEL == "gemini-3.5-flash-lite"
    assert DEFAULT_PARSE_MODEL == "google:gemini-3.8-flash"


def test_denorm_uses_thousand_scale():
    assert _denorm_coord(500, 1440) == 720


def test_normalize_3x_click_keeps_intent():
    class Call:
        name = "click"
        args = {"x": 500, "y": 250, "intent": "Click Grant access"}

    action = _normalize_cu_action(Call(), (1440, 900))
    assert action["name"] == "click"
    assert action["intent"] == "Click Grant access"
    assert action["args"]["x"] == 720
    assert action["args"]["y"] == 225


def test_prune_old_screenshots_keeps_three():
    class FR:
        def __init__(self, name: str):
            self.name = name
            self.parts = ["png"]

    class Part:
        def __init__(self, name: str):
            self.function_response = FR(name)

    class Content:
        def __init__(self, role: str, name: str = "click"):
            self.role = role
            self.parts = [Part(name)]

    contents = [Content("user") for _ in range(5)]
    prune_old_screenshots(contents, keep=MAX_RECENT_TURN_WITH_SCREENSHOTS)
    kept = [c.parts[0].function_response.parts for c in contents]
    assert kept == [None, None, ["png"], ["png"], ["png"]]


def test_loop_applies_all_actions_from_next_actions(grant):
    clicks = []

    class Mouse:
        def click(self, x, y):
            clicks.append((x, y))

    class Client:
        def next_actions(self, screenshot_png, goal):
            return [
                {"name": "click", "args": {"x": 1, "y": 2}, "intent": "a", "safety": "allowed"},
                {"name": "click", "args": {"x": 3, "y": 4}, "intent": "b", "safety": "allowed"},
            ]

    class Page:
        mouse = Mouse()

        def screenshot(self, type="png"):
            return b"png"

    result = run_computer_use_loop(grant, Page(), Client(), max_turns=1)
    assert clicks == [(1, 2), (3, 4)]
    assert result["reason"] == "turn_budget"
    assert result["turn_count"] == 1


def test_highlight_mouse_draws_when_enabled(monkeypatch):
    from computer_use import highlight_mouse

    seen = []

    class Page:
        def evaluate(self, script, arg):
            seen.append(arg)

        def wait_for_timeout(self, ms):
            seen.append(ms)

    monkeypatch.setenv("EXECUTE_HIGHLIGHT_MOUSE", "1")
    monkeypatch.setenv("EXECUTE_CURSOR_MS", "50")
    highlight_mouse(Page(), 10, 20)
    assert [10.0, 20.0] in seen
    assert 50 in seen


def test_apply_3x_go_back():
    calls = []

    class Page:
        def go_back(self):
            calls.append("back")

    _apply_page_action(Page(), {"name": "go_back", "args": {}})
    assert calls == ["back"]


def test_goal_names_resource_principal_and_expiry(grant):
    text = grant_goal(grant)
    assert "bucket-analytics-raw" in text
    assert "u-newhire-1" in text
    assert "Do not grant any other resource" in text


def test_revoke_goal_names_resource_principal_and_remove(grant):
    text = revoke_goal(grant)
    assert "bucket-analytics-raw" in text
    assert "u-newhire-1" in text
    assert "Remove" in text
    assert "Do not grant any other resource" in text


def test_browse_goal_names_object_and_preview(grant):
    text = browse_goal(grant)
    assert "events/2026-09-18.parquet" in text
    assert "#object-preview" in text


def test_query_goal_names_dataset_and_results(grant):
    text = query_goal(grant)
    assert "project-x-finance" in text
    assert "#query-results" in text


def test_enact_goal_contains_selectors_for_each_action(grant):
    assert enact_goal(grant, "grant") == grant_goal(grant)
    assert enact_goal(grant, "revoke") == revoke_goal(grant)
    browse = enact_goal(grant, "browse")
    assert browse == browse_goal(grant)
    assert "events/2026-09-18.parquet" in browse
    assert "#object-preview" in browse
    query = enact_goal(grant, "query")
    assert query == query_goal(grant)
    assert "project-x-finance" in query
    assert "#query-results" in query


def test_enact_goal_rejects_unknown_action(grant):
    with pytest.raises(ValueError):
        enact_goal(grant, "export")


def test_host_allowed_rejects_unknown():
    assert host_allowed("http://127.0.0.1:8765/", allowlist=["127.0.0.1", "localhost"]) is True
    assert host_allowed("https://evil.example/", allowlist=["127.0.0.1"]) is False


def test_host_allowed_reads_env(monkeypatch):
    monkeypatch.delenv("CONSOLE_URL", raising=False)
    monkeypatch.setenv("CONSOLE_ALLOWED_HOSTS", "foo.modal.run, bar.example")
    assert host_allowed("https://foo.modal.run/x") is True
    assert host_allowed("https://bar.example/console") is True
    assert host_allowed("https://evil.example/") is False


def test_host_allowed_includes_console_url_host(monkeypatch):
    monkeypatch.delenv("CONSOLE_ALLOWED_HOSTS", raising=False)
    monkeypatch.setenv("CONSOLE_URL", "https://tunnel.example:443/console")
    assert host_allowed("https://tunnel.example/other") is True
    assert host_allowed("https://evil.example/") is False


def test_verify_active_reads_data_attributes(grant):
    html = '<ul id="active-grants"><li data-resource="bucket-analytics-raw" data-principal="u-newhire-1">ok</li></ul>'
    assert verify_active(html, grant) is True
    assert verify_active("<ul id='active-grants'></ul>", grant) is False


def test_verify_inactive_reads_data_attributes(grant):
    html = '<ul id="active-grants"><li data-resource="bucket-analytics-raw" data-principal="u-newhire-1">ok</li></ul>'
    assert verify_inactive(html, grant) is False
    assert verify_inactive("<ul id='active-grants'></ul>", grant) is True
    other = (
        '<ul id="active-grants">'
        '<li data-resource="bq-project-x-finance" data-principal="u-newhire-1">x</li>'
        "</ul>"
    )
    assert verify_inactive(other, grant) is True


def test_completed_event_shape(grant):
    event = completed_event(
        grant,
        success=False,
        reason="turn_budget",
        actions=[{"intent": "click Grant access", "name": "click", "args": {}}],
        watch_url=None,
        mode="playwright",
        turn_count=20,
    )
    assert event.type.value == "action_executed"
    assert event.actor == "agent"
    assert event.payload["phase"] == "completed"
    assert event.payload["success"] is False
    assert event.payload["reason"] == "turn_budget"
    assert event.payload["action"] == "grant"
    assert event.grant_id == grant.id


def test_completed_event_includes_revoke_action(grant):
    event = completed_event(
        grant,
        success=True,
        reason=None,
        actions=[],
        watch_url=None,
        mode="playwright",
        turn_count=1,
        action="revoke",
    )
    assert event.payload["action"] == "revoke"
    assert event.payload["success"] is True


def test_completed_event_detail_uses_action_name(grant):
    ok = completed_event(
        grant,
        success=True,
        reason=None,
        actions=[],
        watch_url=None,
        mode="computer_use",
        turn_count=1,
        action="browse",
    )
    assert ok.detail == "completed browse bucket-analytics-raw"
    failed = completed_event(
        grant,
        success=False,
        reason="verify_failed",
        actions=[],
        watch_url=None,
        mode="computer_use",
        turn_count=1,
        action="query",
    )
    assert failed.detail == "query execution failed: verify_failed"


def test_playwright_execute_grant_marks_active(grant):
    server, url = _serve_console()
    try:
        event = execute_grant(grant, url, mode="playwright")
        assert event.payload["phase"] == "completed"
        assert event.payload["success"] is True
        assert event.payload["mode"] == "playwright"
        assert event.payload["action"] == "grant"
    finally:
        server.shutdown()


def test_playwright_execute_grant_then_revoke_marks_inactive(grant):
    server, url = _serve_console()
    try:
        granted = execute_grant(grant, url, mode="playwright")
        assert granted.payload["success"] is True
        assert granted.payload["action"] == "grant"
        revoked = execute_grant(grant, url, mode="playwright", action="revoke")
        assert revoked.payload["phase"] == "completed"
        assert revoked.payload["success"] is True
        assert revoked.payload["mode"] == "playwright"
        assert revoked.payload["action"] == "revoke"
    finally:
        server.shutdown()


def test_playwright_writes_video_when_record_dir_set(grant, monkeypatch, tmp_path):
    monkeypatch.setenv("EXECUTE_RECORD_DIR", str(tmp_path))
    monkeypatch.setenv("EXECUTE_SLOW_MO", "0")
    server, url = _serve_console()
    try:
        event = execute_grant(grant, url, mode="playwright")
        assert event.payload["success"] is True
        video = event.payload.get("video_path")
        assert video
        assert video.endswith(".webm")
        assert Path(video).is_file()
        assert Path(video).stat().st_size > 0
    finally:
        server.shutdown()


def test_loop_stops_on_blocked(grant):
    class Client:
        def next_action(self, screenshot_png, goal):
            return {"name": "click", "args": {"x": 1, "y": 1}, "intent": "nope", "safety": "blocked"}

    class Page:
        def screenshot(self, type="png"):
            return b"png"

        def mouse(self):
            raise AssertionError("should not click when blocked")

    result = run_computer_use_loop(grant, Page(), Client(), max_turns=5)
    assert result["success"] is False
    assert result["reason"] == "blocked"


def test_loop_turn_budget(grant):
    class Client:
        def next_action(self, screenshot_png, goal):
            return {"name": "wait", "args": {}, "intent": "look", "safety": "allowed"}

    class Page:
        def screenshot(self, type="png"):
            return b"png"

    result = run_computer_use_loop(grant, Page(), Client(), max_turns=3)
    assert result["reason"] == "turn_budget"
    assert result["turn_count"] == 3


def test_loop_publishes_turn_frame(grant):
    seen = []

    class Client:
        def next_action(self, screenshot_png, goal):
            return None

    class Page:
        def screenshot(self, type="png", quality=None):
            return b"jpeg-bytes"

        def content(self):
            return (
                '<ul id="active-grants">'
                '<li data-resource="bucket-analytics-raw" data-principal="u-newhire-1">ok</li>'
                "</ul>"
            )

    def on_frame(turn, data, mime, action=None):
        seen.append((turn, data, mime, action))
        return f"/cu/frames/t{turn}.jpg"

    result = run_computer_use_loop(grant, Page(), Client(), on_frame=on_frame)
    assert result["success"] is True
    assert seen == [(1, b"jpeg-bytes", "image/jpeg", "verify")]


def test_loop_uses_enact_goal_for_action(grant):
    seen: list[str] = []

    class Client:
        def next_action(self, screenshot_png, goal):
            seen.append(goal)
            return None

    class Page:
        def screenshot(self, type="png"):
            return b"png"

        def content(self):
            return "<ul id='active-grants'></ul>"

    run_computer_use_loop(grant, Page(), Client(), action="browse")
    assert seen
    assert "events/2026-09-18.parquet" in seen[0]
    assert "#object-preview" in seen[0]


def test_loop_none_verifies_then_succeeds(grant):
    class Client:
        def next_action(self, screenshot_png, goal):
            return None

    class Page:
        def screenshot(self, type="png"):
            return b"png"

        def content(self):
            return (
                '<ul id="active-grants">'
                '<li data-resource="bucket-analytics-raw" data-principal="u-newhire-1">ok</li>'
                "</ul>"
            )

    result = run_computer_use_loop(grant, Page(), Client(), max_turns=5)
    assert result["success"] is True
    assert result["reason"] is None


def test_loop_require_confirmation_allowed_on_localhost(grant):
    clicks = []

    class Mouse:
        def click(self, x, y):
            clicks.append((x, y))

    class Client:
        def next_action(self, screenshot_png, goal):
            return {
                "name": "click",
                "args": {"x": 4, "y": 5},
                "intent": "maybe",
                "safety": "require_confirmation",
            }

    class Page:
        url = "http://127.0.0.1:8765/"
        mouse = Mouse()

        def screenshot(self, type="png"):
            return b"png"

    result = run_computer_use_loop(grant, Page(), Client(), max_turns=1)
    assert clicks == [(4, 5)]
    assert result["reason"] == "turn_budget"


def test_execute_grant_computer_use_missing_key_is_unavailable(grant, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINIAPIKEY", raising=False)
    event = execute_grant(grant, "http://127.0.0.1:8765/", mode="computer_use")
    assert event.payload["success"] is False
    assert event.payload["reason"] == "gemini_unavailable"
    assert event.payload["phase"] == "completed"


def test_sandbox_id_default_and_env(monkeypatch):
    from computer_use import current_sandbox_id

    monkeypatch.delenv("SANDBOX_ID", raising=False)
    monkeypatch.delenv("MODAL_TASK_ID", raising=False)
    monkeypatch.delenv("MODAL_FUNCTION_CALL_ID", raising=False)
    assert current_sandbox_id() == "local"
    monkeypatch.setenv("SANDBOX_ID", "sb-9")
    assert current_sandbox_id() == "sb-9"


def test_capture_screenshot_defaults_to_jpeg(monkeypatch):
    from computer_use import capture_screenshot

    seen = {}

    class Page:
        def screenshot(self, type="png", quality=None):
            seen["type"] = type
            seen["quality"] = quality
            return b"jpg"

    monkeypatch.delenv("CU_SCREENSHOT_TYPE", raising=False)
    data, mime = capture_screenshot(Page())
    assert data == b"jpg"
    assert mime == "image/jpeg"
    assert seen["type"] == "jpeg"
