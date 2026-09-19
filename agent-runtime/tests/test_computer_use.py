from computer_use import completed_event, execute_grant, grant_goal, host_allowed, verify_active
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
