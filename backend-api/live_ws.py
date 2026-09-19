"""Drop-in GET/WS /agent/live/ws — relay mic and typed text through Gemini Live.

Mount later with mount_live_ws(app). Tests inject LIVE_CONNECT_IMPL so pytest
never opens a real Gemini session. The API key never appears on the socket.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import sys
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

LIVE_CONNECT_IMPL: Callable | None = None

_FALLBACK_INSTRUCTION = (
    "You are Aperture's assistant agent, not a person. "
    "Speak naturally and briefly. Never grant."
)
_SECRET_FIELDS = frozenset(
    {
        "api_key",
        "apikey",
        "gemini_api_key",
        "gemini_key",
        "google_api_key",
        "key",
    }
)


def _agent_runtime_on_path() -> None:
    runtime = str(Path(__file__).resolve().parents[1] / "agent-runtime")
    if runtime not in sys.path:
        sys.path.append(runtime)


def _known_requesters() -> dict:
    import main

    return main.KNOWN_REQUESTERS


def _viewer_console_role(viewer: Any) -> str:
    if re.search(r"manager|owner|lead|head", getattr(viewer, "role", None) or "", re.I):
        return "manager"
    return "user"


def _normalize_focus(focus_id: str | None) -> str | None:
    if focus_id is None:
        return None
    key = focus_id.strip()
    if not key or key.lower() in {"all", "everyone"}:
        return None
    return key


def _env_secrets() -> set[str]:
    return {
        value
        for value in (
            os.environ.get("GEMINI_API_KEY"),
            os.environ.get("GOOGLE_API_KEY"),
            os.environ.get("GOOGLE_GENAI_API_KEY"),
        )
        if value
    }


def _is_secret_field(name: str) -> bool:
    folded = name.lower().replace("-", "_")
    return folded in _SECRET_FIELDS or "api_key" in folded


def _strip_secrets(value: Any, secrets: set[str]) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _is_secret_field(str(key)):
                continue
            cleaned[key] = _strip_secrets(item, secrets)
        return cleaned
    if isinstance(value, list):
        return [_strip_secrets(item, secrets) for item in value]
    if isinstance(value, str) and secrets:
        for secret in secrets:
            if secret and secret in value:
                value = value.replace(secret, "")
        return value
    return value


def _live_model() -> str:
    _agent_runtime_on_path()
    try:
        from gemini_models import live_model

        return live_model()
    except ImportError:
        try:
            from live_session import live_model as session_live_model

            return session_live_model()
        except ImportError:
            return "gemini-2.5-flash-native-audio"


def _system_instruction(context: dict) -> str:
    _agent_runtime_on_path()
    try:
        from live_session import live_instruction
    except ImportError:
        return _FALLBACK_INSTRUCTION
    try:
        return live_instruction(context)
    except Exception:
        return _FALLBACK_INSTRUCTION


def _invoke_factory(factory: Callable, context: dict) -> Any:
    try:
        sig = inspect.signature(factory)
    except (TypeError, ValueError):
        return factory()
    params = [
        p
        for p in sig.parameters.values()
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    if not params:
        return factory()
    return factory(context)


@asynccontextmanager
async def _enter_impl(context: dict) -> AsyncIterator[Any]:
    impl = LIVE_CONNECT_IMPL
    if impl is None:
        raise RuntimeError("LIVE_CONNECT_IMPL is not set")
    target: Any = impl
    if not hasattr(target, "__aenter__") and callable(target):
        target = _invoke_factory(target, context)
        if inspect.isawaitable(target):
            target = await target
    if hasattr(target, "__aenter__"):
        async with target as session:
            yield session
    else:
        yield target


class _GeminiSession:
    """Adapt google.genai Live session to send_audio / send_text / receive()."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    async def send_audio(self, data: bytes) -> None:
        from google.genai import types

        await self._raw.send_realtime_input(
            audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
        )

    async def send_text(self, text: str) -> None:
        await self._raw.send_realtime_input(text=text)

    async def receive(self) -> AsyncIterator[dict]:
        async for msg in self._raw.receive():
            data = getattr(msg, "data", None)
            text = getattr(msg, "text", None)
            if data:
                yield {"kind": "audio", "data": data}
            if text:
                yield {"kind": "text", "text": text}
            sc = getattr(msg, "server_content", None)
            if sc is None:
                continue
            for attr, kind, role in (
                ("input_transcription", "input_transcript", "you"),
                ("interim_input_transcription", "input_transcript", "you"),
                ("output_transcription", "output_transcript", "gemini"),
            ):
                part = getattr(sc, attr, None)
                spoken = getattr(part, "text", None) if part is not None else None
                if spoken:
                    yield {"kind": kind, "role": role, "text": spoken}
            if getattr(sc, "interrupted", False):
                yield {"kind": "interrupted"}
            elif getattr(sc, "turn_complete", False):
                yield {"kind": "turn_complete"}


@asynccontextmanager
async def _gemini_connect(context: dict) -> AsyncIterator[Any]:
    from google import genai
    from google.genai import types

    model = _live_model()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=_system_instruction(context),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
            )
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=False,
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                silence_duration_ms=400,
            )
        ),
    )
    async with client.aio.live.connect(model=model, config=config) as raw:
        yield _GeminiSession(raw)


@asynccontextmanager
async def _open_session(context: dict) -> AsyncIterator[Any]:
    if LIVE_CONNECT_IMPL is not None:
        async with _enter_impl(context) as session:
            yield session
        return
    async with _gemini_connect(context) as session:
        yield session


async def _iter_session(session: Any) -> AsyncIterator[dict]:
    stream = session.receive()
    if inspect.isawaitable(stream):
        stream = await stream
    async for item in stream:
        yield item


async def _send_json(websocket: WebSocket, lock: asyncio.Lock, payload: dict) -> None:
    cleaned = _strip_secrets(payload, _env_secrets())
    async with lock:
        await websocket.send_json(cleaned)


async def _send_bytes(websocket: WebSocket, lock: asyncio.Lock, data: bytes) -> None:
    async with lock:
        await websocket.send_bytes(data)


async def _send_mode(websocket: WebSocket, lock: asyncio.Lock, mode: str) -> None:
    await _send_json(websocket, lock, {"type": "mode", "mode": mode})


async def _send_error(websocket: WebSocket, lock: asyncio.Lock, message: str) -> None:
    await _send_json(websocket, lock, {"type": "error", "message": message})


async def _pump_client(
    websocket: WebSocket, session: Any, lock: asyncio.Lock, state: dict
) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        data = message.get("bytes")
        if data is not None:
            if state.get("speaking"):
                continue
            await session.send_audio(data)
            continue
        text = message.get("text")
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            await _send_error(websocket, lock, "invalid json")
            continue
        if payload.get("type") != "text":
            continue
        spoken = str(payload.get("text") or "")
        await session.send_text(spoken)
        await _send_json(
            websocket, lock, {"type": "transcript", "role": "you", "text": spoken}
        )
        await _send_mode(websocket, lock, "thinking")


async def _pump_session(
    websocket: WebSocket, session: Any, lock: asyncio.Lock, state: dict
) -> None:
    async for item in _iter_session(session):
        kind = item.get("kind")
        if kind == "audio" and item.get("data") is not None:
            state["speaking"] = True
            await _send_mode(websocket, lock, "speaking")
            await _send_bytes(websocket, lock, item["data"])
        elif kind in {"input_transcript", "output_transcript", "text"} and item.get("text"):
            role = item.get("role") or (
                "you" if kind == "input_transcript" else "gemini"
            )
            await _send_json(
                websocket,
                lock,
                {"type": "transcript", "role": role, "text": item["text"]},
            )
        elif kind in {"turn_complete", "interrupted"}:
            state["speaking"] = False
            await _send_mode(websocket, lock, "listening")
        elif kind == "error":
            await _send_error(
                websocket,
                lock,
                str(item.get("text") or item.get("message") or "live error"),
            )


async def _relay(websocket: WebSocket, session: Any, lock: asyncio.Lock) -> None:
    state = {"speaking": False}
    client_task = asyncio.create_task(_pump_client(websocket, session, lock, state))
    session_task = asyncio.create_task(_pump_session(websocket, session, lock, state))
    done, pending = await asyncio.wait(
        {client_task, session_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    for task in pending:
        try:
            await task
        except (asyncio.CancelledError, WebSocketDisconnect):
            pass
    for task in done:
        exc = task.exception()
        if exc and not isinstance(exc, (WebSocketDisconnect, asyncio.CancelledError)):
            raise exc


async def _read_hello(websocket: WebSocket) -> dict | None:
    try:
        raw = await websocket.receive_text()
    except WebSocketDisconnect:
        return None
    try:
        hello = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(hello, dict) or hello.get("type") != "hello":
        return None
    return hello


async def live_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    lock = asyncio.Lock()
    try:
        hello = await _read_hello(websocket)
        if hello is None:
            await websocket.close(code=4400)
            return
        viewer_id = str(hello.get("viewer_id") or "").strip()
        viewer = _known_requesters().get(viewer_id) if viewer_id else None
        if viewer is None:
            await websocket.close(code=4400)
            return
        if LIVE_CONNECT_IMPL is None and not os.environ.get("GEMINI_API_KEY"):
            await _send_error(websocket, lock, "live offline")
            await websocket.close(code=4401)
            return

        conversation_id = (str(hello.get("conversation_id") or "")).strip() or str(
            uuid.uuid4()
        )
        context = {
            "actor_id": viewer.id,
            "focus_id": _normalize_focus(hello.get("focus_id")),
            "page": hello.get("page") or "overview",
            "role": _viewer_console_role(viewer),
            "conversation_id": conversation_id,
        }
        async with _open_session(context) as session:
            await _send_json(
                websocket,
                lock,
                {
                    "type": "ready",
                    "conversation_id": conversation_id,
                    "model": _live_model(),
                },
            )
            await _send_mode(websocket, lock, "listening")
            await _relay(websocket, session, lock)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        try:
            await _send_error(websocket, lock, str(exc) or "live error")
        except Exception:
            pass
        try:
            await websocket.close(code=1011)
        except Exception:
            return


def mount_live_ws(app: FastAPI) -> None:
    app.add_api_websocket_route("/agent/live/ws", live_ws)
