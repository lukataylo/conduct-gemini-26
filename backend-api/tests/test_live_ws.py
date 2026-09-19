import asyncio
import json
import threading
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import live_ws
from live_ws import mount_live_ws

ALEX_ID = "u-newhire-1"
SECRET = "secret-gemini-key"


@pytest.fixture(autouse=True)
def reset_impl():
    live_ws.LIVE_CONNECT_IMPL = None
    yield
    live_ws.LIVE_CONNECT_IMPL = None


def _client() -> TestClient:
    app = FastAPI()
    mount_live_ws(app)
    return TestClient(app)


class MockSession:
    def __init__(self, outgoing: list[dict] | None = None) -> None:
        self.texts: list[str] = []
        self.audios: list[bytes] = []
        self._q: asyncio.Queue = asyncio.Queue()
        for item in outgoing or []:
            self._q.put_nowait(item)

    async def send_text(self, text: str) -> None:
        self.texts.append(text)

    async def send_audio(self, data: bytes) -> None:
        self.audios.append(data)

    async def receive(self):
        while True:
            item = await self._q.get()
            if item is None:
                return
            yield item


def _install(session: MockSession, outgoing: list[dict] | None = None) -> MockSession:
    if outgoing:
        for item in outgoing:
            session._q.put_nowait(item)

    @asynccontextmanager
    async def impl():
        yield session

    live_ws.LIVE_CONNECT_IMPL = impl
    return session


def _recv_json(ws, typ: str, limit: int = 20) -> dict:
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("type") == typ:
            return msg
    raise AssertionError(f"did not receive json type={typ!r}")


def _recv_or_none(ws, timeout: float = 0.6):
    box: dict = {}

    def run() -> None:
        try:
            box["msg"] = ws.receive()
        except Exception as exc:  # noqa: BLE001 — test helper
            box["err"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None
    return box.get("msg")


def _recv_bytes(ws, limit: int = 20) -> bytes:
    for _ in range(limit):
        message = ws.receive()
        if message.get("bytes") is not None:
            return message["bytes"]
    raise AssertionError("did not receive binary frame")


def _expect_close(ws, code: int) -> None:
    try:
        while True:
            message = ws.receive()
            if message.get("type") == "websocket.close":
                assert message["code"] == code
                return
    except WebSocketDisconnect as exc:
        assert exc.code == code
        return
    pytest.fail(f"expected websocket close {code}")


def test_offline_without_impl_or_key_closes_4401(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with _client().websocket_connect("/agent/live/ws") as ws:
        ws.send_json({"type": "hello", "viewer_id": ALEX_ID})
        err = _recv_json(ws, "error")
        assert err["message"] == "live offline"
        _expect_close(ws, 4401)


def test_unknown_viewer_closes_4400():
    called: list = []

    @asynccontextmanager
    async def impl():
        called.append(True)
        yield MockSession()

    live_ws.LIVE_CONNECT_IMPL = impl
    with _client().websocket_connect("/agent/live/ws") as ws:
        ws.send_json({"type": "hello", "viewer_id": "no-such-user"})
        _expect_close(ws, 4400)
    assert called == []


def test_hello_ready_never_includes_api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    _install(MockSession())
    with _client().websocket_connect("/agent/live/ws") as ws:
        ws.send_json(
            {
                "type": "hello",
                "viewer_id": ALEX_ID,
                "conversation_id": "c-live-1",
            }
        )
        ready = _recv_json(ws, "ready")
    assert ready["type"] == "ready"
    assert ready["conversation_id"] == "c-live-1"
    assert "model" in ready
    assert "api_key" not in ready
    dumped = json.dumps(ready)
    assert SECRET not in dumped
    assert "api_key" not in dumped


def test_text_hello_is_forwarded_to_send_text():
    session = _install(MockSession())
    with _client().websocket_connect("/agent/live/ws") as ws:
        ws.send_json({"type": "hello", "viewer_id": ALEX_ID})
        _recv_json(ws, "ready")
        ws.send_json({"type": "text", "text": "hello"})
        you = _recv_json(ws, "transcript")
        assert you["role"] == "you"
        assert you["text"] == "hello"
        assert session.texts == ["hello"]


def test_binary_audio_is_forwarded_to_send_audio():
    session = _install(MockSession())
    chunk = b"\x01\x00\x02\x00"
    with _client().websocket_connect("/agent/live/ws") as ws:
        ws.send_json({"type": "hello", "viewer_id": ALEX_ID})
        _recv_json(ws, "ready")
        _recv_json(ws, "mode")
        ws.send_bytes(chunk)
        ws.send_json({"type": "text", "text": "probe"})
        you = _recv_json(ws, "transcript")
        assert you["text"] == "probe"
        assert session.audios == [chunk]


def test_pcm_does_not_restamp_listening():
    """Mic chunks must not force LISTENING — that wipes Gemini playback and hides end-of-speech."""
    session = _install(MockSession())
    chunk = b"\x00\x00" * 160
    with _client().websocket_connect("/agent/live/ws") as ws:
        ws.send_json({"type": "hello", "viewer_id": ALEX_ID})
        _recv_json(ws, "ready")
        assert _recv_json(ws, "mode")["mode"] == "listening"
        ws.send_bytes(chunk)
        ws.send_json({"type": "text", "text": "x"})
        modes: list[str] = []
        for _ in range(8):
            msg = ws.receive_json()
            if msg.get("type") == "mode":
                modes.append(msg["mode"])
            if msg.get("type") == "transcript":
                break
        assert "listening" not in modes
        assert session.audios == [chunk]


def test_turn_complete_returns_to_listening():
    pcm = b"\x03\x00\x04\x00"
    _install(
        MockSession(
            outgoing=[
                {"kind": "audio", "data": pcm},
                {"kind": "turn_complete"},
            ]
        )
    )
    with _client().websocket_connect("/agent/live/ws") as ws:
        ws.send_json({"type": "hello", "viewer_id": ALEX_ID})
        _recv_json(ws, "ready")
        assert _recv_json(ws, "mode")["mode"] == "listening"
        assert _recv_json(ws, "mode")["mode"] == "speaking"
        assert _recv_bytes(ws) == pcm
        nxt = _recv_or_none(ws)
        assert nxt is not None
        payload = nxt.get("text")
        data = json.loads(payload) if isinstance(payload, str) else payload
        assert data == {"type": "mode", "mode": "listening"}


def test_speaking_drops_followup_mic():
    """While Gemini is talking, do not feed the laptop mic back in (echo keeps VAD open)."""
    pcm = b"\x09\x00\x0a\x00"
    session = _install(MockSession(outgoing=[{"kind": "audio", "data": pcm}]))
    with _client().websocket_connect("/agent/live/ws") as ws:
        ws.send_json({"type": "hello", "viewer_id": ALEX_ID})
        _recv_json(ws, "ready")
        assert _recv_bytes(ws) == pcm
        ws.send_bytes(b"\x11\x00\x12\x00")
        ws.send_json({"type": "text", "text": "after"})
        _recv_json(ws, "transcript")
        assert session.audios == []


def test_join_transcript_glues_word_pieces():
    from live_ws import join_transcript

    assert join_transcript("He", "llo") == "Hello"
    assert join_transcript("Hello.", "What") == "Hello. What"
    assert join_transcript("Alex", " Chen") == "Alex Chen"


def test_streaming_transcripts_are_one_utterance():
    """Live ASR arrives as word pieces — the bubble must get one line, not one row per word."""
    _install(
        MockSession(
            outgoing=[
                {"kind": "output_transcript", "role": "gemini", "text": "Alex"},
                {"kind": "output_transcript", "role": "gemini", "text": " Chen"},
                {"kind": "output_transcript", "role": "gemini", "text": " has access.", "finished": True},
            ]
        )
    )
    with _client().websocket_connect("/agent/live/ws") as ws:
        ws.send_json({"type": "hello", "viewer_id": ALEX_ID})
        _recv_json(ws, "ready")
        _recv_json(ws, "mode")
        msg = _recv_json(ws, "transcript")
    assert msg == {
        "type": "transcript",
        "role": "gemini",
        "text": "Alex Chen has access.",
    }


def test_two_audio_chunks_speak_once():
    """Restamping speaking every PCM frame remounts the face and breaks the next turns."""
    pcm_a = b"\x01\x00"
    pcm_b = b"\x02\x00"
    _install(MockSession(outgoing=[{"kind": "audio", "data": pcm_a}, {"kind": "audio", "data": pcm_b}]))
    with _client().websocket_connect("/agent/live/ws") as ws:
        ws.send_json({"type": "hello", "viewer_id": ALEX_ID})
        _recv_json(ws, "ready")
        _recv_json(ws, "mode")
        modes: list[str] = []
        got: list[bytes] = []
        for _ in range(8):
            msg = ws.receive()
            if msg.get("bytes") is not None:
                got.append(msg["bytes"])
                if len(got) == 2:
                    break
                continue
            payload = msg.get("text")
            if not payload:
                continue
            data = json.loads(payload) if isinstance(payload, str) else payload
            if data.get("type") == "mode":
                modes.append(data["mode"])
        assert modes == ["speaking"]
        assert got == [pcm_a, pcm_b]


def test_input_transcript_is_you():
    _install(
        MockSession(
            outgoing=[
                {"kind": "input_transcript", "text": "who is waiting", "finished": True}
            ]
        )
    )
    with _client().websocket_connect("/agent/live/ws") as ws:
        ws.send_json({"type": "hello", "viewer_id": ALEX_ID})
        _recv_json(ws, "ready")
        _recv_json(ws, "mode")
        nxt = _recv_or_none(ws)
        assert nxt is not None
        payload = nxt.get("text")
        data = json.loads(payload) if isinstance(payload, str) else payload
    assert data == {"type": "transcript", "role": "you", "text": "who is waiting"}


def test_mock_audio_comes_back_as_ws_binary():
    pcm = b"\x03\x00\x04\x00\x05\x00"
    _install(MockSession(outgoing=[{"kind": "audio", "data": pcm}]))
    with _client().websocket_connect("/agent/live/ws") as ws:
        ws.send_json({"type": "hello", "viewer_id": ALEX_ID})
        _recv_json(ws, "ready")
        assert _recv_bytes(ws) == pcm


def test_speech_button_starts_live_conversation():
    """Mic press in the UI: hello, then PCM — Gemini Live session is running."""
    session = _install(MockSession())
    chunk = b"\x00\x00" * 160
    with _client().websocket_connect("/agent/live/ws") as ws:
        ws.send_json(
            {
                "type": "hello",
                "viewer_id": ALEX_ID,
                "page": "overview",
                "conversation_id": "c-mic",
            }
        )
        ready = _recv_json(ws, "ready")
        assert ready["conversation_id"] == "c-mic"
        listening = _recv_json(ws, "mode")
        assert listening["mode"] == "listening"
        ws.send_bytes(chunk)
        ws.send_json({"type": "text", "text": "probe"})
        assert _recv_json(ws, "transcript")["text"] == "probe"
        assert session.audios == [chunk]
        assert "api_key" not in json.dumps(ready)


def test_mock_transcript_comes_back_as_type_transcript():
    _install(MockSession(outgoing=[{"kind": "text", "text": "hi from gemini"}]))
    with _client().websocket_connect("/agent/live/ws") as ws:
        ws.send_json({"type": "hello", "viewer_id": ALEX_ID})
        _recv_json(ws, "ready")
        msg = _recv_json(ws, "transcript")
    assert msg == {"type": "transcript", "role": "gemini", "text": "hi from gemini"}
