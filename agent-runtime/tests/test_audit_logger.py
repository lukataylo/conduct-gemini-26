from audit_logger import local_events, log, reset, set_emitter
from shared.schemas import AuditEventType


def test_log_includes_trace_id():
    reset()
    event = log(
        AuditEventType.ACTION_EXECUTED,
        actor="agent",
        detail="started",
        request_id="r-1",
        grant_id="g-1",
        trace_id="trace-abc",
        payload={"phase": "started"},
    )
    assert event.trace_id == "trace-abc"
    assert local_events()[0].trace_id == "trace-abc"


def test_reset_clears_sink_and_emitter():
    seen = []
    set_emitter(seen.append)
    log(AuditEventType.ACTION_EXECUTED, actor="agent", detail="x")
    reset()
    seen.clear()
    assert local_events() == []
    log(AuditEventType.ACTION_EXECUTED, actor="agent", detail="y")
    assert seen == []  # emitter cleared
