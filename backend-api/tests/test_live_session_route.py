import sys
import types
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import live_session_route
from live_session_route import mount_live_session

ALEX_ID = "u-newhire-1"
PRIYA_ID = "u-manager-1"
JORDAN_ID = "u-finance-owner-1"


@pytest.fixture(autouse=True)
def reset_impl():
    live_session_route.LIVE_SESSION_IMPL = None
    yield
    live_session_route.LIVE_SESSION_IMPL = None


def _client() -> TestClient:
    app = FastAPI()
    mount_live_session(app)
    return TestClient(app)


def test_unknown_viewer_is_400():
    called: list = []

    def impl(context, conversation_id):
        called.append((context, conversation_id))
        return {"ok": True, "conversation_id": conversation_id}

    live_session_route.LIVE_SESSION_IMPL = impl
    resp = _client().post("/agent/live/session", json={"viewer_id": "no-such-user"})
    assert resp.status_code == 400
    assert "unknown requester" in resp.json()["detail"]
    assert called == []


def test_keeps_provided_conversation_id():
    seen: dict = {}

    def impl(context, conversation_id):
        seen["context"] = context
        seen["conversation_id"] = conversation_id
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "model": "gemini-2.5-flash-native-audio",
        }

    live_session_route.LIVE_SESSION_IMPL = impl
    resp = _client().post(
        "/agent/live/session",
        json={
            "viewer_id": PRIYA_ID,
            "focus_id": JORDAN_ID,
            "page": "timeline",
            "conversation_id": "c-chat-1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"] == "c-chat-1"
    assert body["ok"] is True
    assert seen["conversation_id"] == "c-chat-1"
    assert seen["context"]["actor_id"] == PRIYA_ID
    assert seen["context"]["focus_id"] == JORDAN_ID
    assert seen["context"]["page"] == "timeline"
    assert seen["context"]["role"] == "manager"


def test_mints_conversation_id_when_missing():
    live_session_route.LIVE_SESSION_IMPL = lambda ctx, cid: {
        "ok": True,
        "conversation_id": cid,
        "model": "gemini-2.5-flash-native-audio",
    }
    resp = _client().post("/agent/live/session", json={"viewer_id": ALEX_ID})
    assert resp.status_code == 200
    minted = resp.json()["conversation_id"]
    assert uuid.UUID(minted)


def test_api_key_never_in_response(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-gemini-key")

    def impl(context, conversation_id):
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "model": "gemini-2.5-flash-native-audio",
            "api_key": "secret-gemini-key",
            "GEMINI_API_KEY": "secret-gemini-key",
            "fallback": None,
        }

    live_session_route.LIVE_SESSION_IMPL = impl
    resp = _client().post(
        "/agent/live/session",
        json={"viewer_id": ALEX_ID, "conversation_id": "c-1"},
    )
    assert resp.status_code == 200
    assert "secret-gemini-key" not in resp.text
    body = resp.json()
    assert "api_key" not in body
    assert "GEMINI_API_KEY" not in body


def test_lazy_import_used_when_impl_unset(monkeypatch):
    called: dict = {}

    fake = types.ModuleType("live_session")

    def start_live_session(context, conversation_id):
        called["context"] = context
        called["conversation_id"] = conversation_id
        return {
            "ok": False,
            "conversation_id": conversation_id,
            "fallback": "speech",
            "api_key": "should-not-leak",
        }

    fake.start_live_session = start_live_session
    monkeypatch.setitem(sys.modules, "live_session", fake)

    resp = _client().post(
        "/agent/live/session",
        json={"viewer_id": ALEX_ID, "conversation_id": "c-lazy"},
    )
    assert resp.status_code == 200
    assert called["conversation_id"] == "c-lazy"
    assert called["context"]["actor_id"] == ALEX_ID
    body = resp.json()
    assert body == {
        "ok": False,
        "conversation_id": "c-lazy",
        "model": None,
        "fallback": "speech",
    }
    assert "should-not-leak" not in resp.text
