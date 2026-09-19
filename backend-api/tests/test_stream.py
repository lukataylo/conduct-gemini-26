import main
from shared.schemas import AuditEventType


def test_audit_publishes_grant_issued_and_audit_event():
    seen: list[dict] = []
    main.STREAM_SUBSCRIBERS.append(seen.append)

    main._audit(AuditEventType.GRANT_ISSUED, actor="policy-engine", detail="granted bucket")

    types = {msg["type"] for msg in seen}
    assert "grant_issued" in types
    assert "audit_event" in types
    assert all("event" in msg for msg in seen)
