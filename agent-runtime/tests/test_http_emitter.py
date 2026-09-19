from http_emitter import make_emitter
from shared.schemas import AuditEvent, AuditEventType


class FakeClient:
    def __init__(self):
        self.calls = []

    def post(self, url, json, timeout):
        self.calls.append((url, json, timeout))

        class Resp:
            def raise_for_status(self):
                return None

        return Resp()


def test_emitter_posts_audit_event():
    client = FakeClient()
    emit = make_emitter("http://backend.example.com", client=client)
    event = AuditEvent(
        id="evt-1",
        type=AuditEventType.ACTION_EXECUTED,
        actor="agent",
        detail="started",
        grant_id="g-1",
        request_id="r-1",
        payload={"phase": "started"},
    )
    emit(event)
    assert client.calls[0][0] == "http://backend.example.com/audit"
    assert client.calls[0][1]["id"] == "evt-1"
    assert client.calls[0][1]["type"] == "action_executed"


def test_default_client_is_closeable():
    emit = make_emitter("http://backend.example.com")
    emit.close()


def test_upload_frame_returns_screenshot_url():
    from http_emitter import upload_frame

    class FrameClient:
        def post(self, url, json, timeout):
            assert url == "http://backend.example.com/cu/frames"
            assert json["turn"] == 3

            class Resp:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {"screenshot_url": "/cu/frames/g-1-turn-03.jpg"}

            return Resp()

    url = upload_frame(
        "http://backend.example.com",
        {"grant_id": "g-1", "turn": 3, "data": "xx", "mime": "image/jpeg"},
        client=FrameClient(),
    )
    assert url == "/cu/frames/g-1-turn-03.jpg"
