"""Computer-use frames for the Aperture enact pane.

Live turns POST bytes here; the console polls /cu/preview. When no live session
exists, preview falls back to the newest on-disk recording so the board is never
empty on a laptop that already ran execute_grant.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_TURN_FILE = re.compile(r"turn-(\d+)\.(jpe?g|png)$", re.IGNORECASE)


def frame_dir() -> Path:
    raw = os.environ.get("CU_FRAME_DIR")
    path = Path(raw) if raw else Path(__file__).resolve().parent / ".cu-frames"
    path.mkdir(parents=True, exist_ok=True)
    return path


def replay_dir() -> Path | None:
    raw = os.environ.get("CU_REPLAY_DIR")
    if raw:
        path = Path(raw)
        return path if path.is_dir() else None
    recordings = Path(__file__).resolve().parents[1] / "agent-runtime" / "recordings"
    if not recordings.is_dir():
        return None
    newest: Path | None = None
    newest_mtime = -1.0
    for child in recordings.iterdir():
        if not child.is_dir():
            continue
        if not any(_TURN_FILE.search(p.name) for p in child.iterdir() if p.is_file()):
            continue
        mtime = child.stat().st_mtime
        if mtime > newest_mtime:
            newest = child
            newest_mtime = mtime
    return newest


def save_frame(*, grant_id: str, turn: int, mime: str, data: bytes) -> str:
    if not data:
        raise HTTPException(400, "empty frame")
    if len(data) > 2_000_000:
        raise HTTPException(413, "frame too large")
    ext = "png" if "png" in (mime or "") else "jpg"
    grant = re.sub(r"[^A-Za-z0-9_-]", "", grant_id)[:32] or "grant"
    name = f"{grant}-turn-{int(turn):02d}-{uuid.uuid4().hex[:6]}.{ext}"
    dest = frame_dir() / name
    dest.write_bytes(data)
    return f"/cu/frames/{name}"


def _safe_file(directory: Path, name: str) -> Path:
    if not _SAFE_NAME.fullmatch(name):
        raise HTTPException(400, "invalid frame name")
    path = (directory / name).resolve()
    root = directory.resolve()
    if path != root and root not in path.parents:
        raise HTTPException(404, "frame not found")
    if not path.is_file():
        raise HTTPException(404, "frame not found")
    return path


def file_response(name: str) -> FileResponse:
    path = _safe_file(frame_dir(), name)
    media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media)


def replay_response(name: str) -> FileResponse:
    directory = replay_dir()
    if directory is None:
        raise HTTPException(404, "no replay")
    path = _safe_file(directory, name)
    media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media)


def frames_from_audit(events) -> list[dict]:
    out: list[dict] = []
    for event in events:
        payload = getattr(event, "payload", None) or {}
        url = payload.get("screenshot_url")
        if not url:
            continue
        if getattr(event, "type", None) is not None:
            kind = event.type.value if hasattr(event.type, "value") else str(event.type)
        else:
            kind = ""
        if kind and kind != "action_executed":
            continue
        ts = getattr(event, "timestamp", None)
        out.append(
            {
                "url": url,
                "turn": int(payload.get("turn") or 0),
                "action": payload.get("action") or payload.get("tool") or getattr(event, "detail", None),
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else ts,
                "grant_id": getattr(event, "grant_id", None),
                "source": "live",
            }
        )
    return out


def replay_frames() -> list[dict]:
    directory = replay_dir()
    if directory is None:
        return []
    found: list[tuple[int, Path]] = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        match = _TURN_FILE.search(path.name)
        if match:
            found.append((int(match.group(1)), path))
    found.sort(key=lambda item: item[0])
    return [
        {
            "url": f"/cu/replay/{path.name}",
            "turn": turn,
            "action": f"turn {turn:02d}",
            "timestamp": None,
            "grant_id": None,
            "source": "replay",
        }
        for turn, path in found
    ]


def session_running(events) -> bool:
    """True when a computer-use run started and has not yet completed."""
    started = False
    for event in events:
        phase = (getattr(event, "payload", None) or {}).get("phase")
        if phase == "started":
            started = True
        elif phase == "completed" and started:
            started = False
    return started


def preview(events) -> dict:
    live = frames_from_audit(events)
    if live:
        grant_id = next((f["grant_id"] for f in reversed(live) if f.get("grant_id")), None)
        return {
            "status": "live",
            "grant_id": grant_id,
            "running": session_running(events),
            "frames": live,
        }
    replay = replay_frames()
    if replay:
        return {"status": "replay", "grant_id": None, "running": False, "frames": replay}
    return {"status": "idle", "grant_id": None, "running": False, "frames": []}
