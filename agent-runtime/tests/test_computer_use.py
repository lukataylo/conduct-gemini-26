from computer_use import (
    completed_event,
    execute_grant,
    grant_goal,
    host_allowed,
    run_computer_use_loop,
    verify_active,
)
from mock_console.server import serve_in_thread


def test_goal_names_resource_principal_and_expiry(grant):
    text = grant_goal(grant)
    assert "bucket-analytics-raw" in text
    assert "u-newhire-1" in text
    assert "Do not grant any other resource" in text


def test_host_allowed_rejects_unknown():
    assert host_allowed("http://127.0.0.1:8765/", allowlist=["127.0.0.1", "localhost"]) is True
    assert host_allowed("https://evil.example/", allowlist=["127.0.0.1"]) is False


def test_verify_active_reads_data_attributes(grant):
    html = '<ul id="active-grants"><li data-resource="bucket-analytics-raw" data-principal="u-newhire-1">ok</li></ul>'
    assert verify_active(html, grant) is True
    assert verify_active("<ul id='active-grants'></ul>", grant) is False


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
    assert event.grant_id == grant.id


def test_playwright_execute_grant_marks_active(grant):
    server = serve_in_thread(port=8765)
    try:
        event = execute_grant(grant, "http://127.0.0.1:8765/", mode="playwright")
        assert event.payload["phase"] == "completed"
        assert event.payload["success"] is True
        assert event.payload["mode"] == "playwright"
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
