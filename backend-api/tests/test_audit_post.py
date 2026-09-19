from fastapi.testclient import TestClient
from main import app
from shared.schemas import AuditEventType


def test_post_audit_appends_action_executed():
    client = TestClient(app)
    resp = client.post(
        "/audit",
        json={
            "id": "client-supplied-ignored",
            "type": "action_executed",
            "actor": "agent",
            "detail": "computer-use session started",
            "request_id": "r-1",
            "grant_id": "g-1",
            "payload": {"phase": "started", "watch_url": "https://example/vnc"},
            "trace_id": "lf-1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "action_executed"
    assert body["id"] != "client-supplied-ignored"
    assert body["payload"]["phase"] == "started"
    listed = client.get("/audit").json()
    assert any(e["id"] == body["id"] for e in listed)
