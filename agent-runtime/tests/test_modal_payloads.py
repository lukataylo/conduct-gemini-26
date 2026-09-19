from modal_app import handle_execute, handle_parse
from shared.schemas import AuditEvent, AuditEventType


def test_handle_parse_returns_access_request_dict(requester):
    from gemini_parser import ParseFields  # noqa: F401

    def parse(raw_text, requester, known, runner=None):
        from gemini_parser import _build_request
        return _build_request(raw_text, requester, "atlas-migration", ["bucket-analytics-raw"], 14)

    out = handle_parse(
        {
            "raw_text": "I need analytics-raw",
            "requester": requester.model_dump(),
            "known_resource_ids": ["bucket-analytics-raw"],
        },
        parse=parse,
    )
    assert out["resource_ids"] == ["bucket-analytics-raw"]


def test_handle_execute_calls_execute(grant):
    def execute(g, url, **kw):
        return AuditEvent(
            id="evt",
            type=AuditEventType.ACTION_EXECUTED,
            actor="agent",
            detail="ok",
            grant_id=g.id,
            request_id=g.request_id,
            payload={"phase": "completed", "success": True, "watch_url": None},
        )

    out = handle_execute(
        {"grant": grant.model_dump(mode="json"), "console_url": "http://127.0.0.1:8765/"},
        execute=execute,
    )
    assert out["grant_id"] == grant.id
    assert out["sandbox_id"] == "local"
    assert out["event"]["payload"]["success"] is True


def test_handle_execute_sets_emitter_when_callback(grant, monkeypatch):
    from audit_logger import reset, set_emitter

    reset()
    seen = []

    def fake_make_emitter(callback_base_url, *, client=None):
        seen.append(callback_base_url)

        def emit(event):
            return None

        return emit

    monkeypatch.setattr("modal_app.make_emitter", fake_make_emitter)
    monkeypatch.setattr("http_emitter.make_emitter", fake_make_emitter)

    def execute(g, url, **kw):
        return AuditEvent(
            id="evt",
            type=AuditEventType.ACTION_EXECUTED,
            actor="agent",
            detail="ok",
            grant_id=g.id,
            request_id=g.request_id,
            payload={"phase": "completed", "success": True},
        )

    out = handle_execute(
        {
            "grant": grant.model_dump(mode="json"),
            "console_url": "http://127.0.0.1:8765/",
            "callback_base_url": "http://backend.example.com",
            "watch_url": "http://watch.example/",
        },
        execute=execute,
    )
    assert seen == ["http://backend.example.com"]
    assert out["watch_url"] == "http://watch.example/"
    set_emitter(None)
    reset()
