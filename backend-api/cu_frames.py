"""Computer-use frames for the Aperture enact pane.

Live turns POST bytes here; the console polls /cu/preview. Replay stills are
grouped by recording session (folder) and stem (computer_use vs playwright).
Video/gif recordings stay off the stills strip.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_STILL = re.compile(
    r"^(?P<stem>.+?)-(?P<kind>turn|frame)-(?P<n>\d+)\.(?P<ext>jpe?g|png)$",
    re.IGNORECASE,
)
_VIDEO = re.compile(r"^(?P<stem>.+)\.(?P<ext>webm|gif|mp4)$", re.IGNORECASE)
_SESSION_STAMP = re.compile(r"^(?P<date>\d{8})-(?P<time>\d{6})(?:-(?P<tag>.+))?$")


def frame_dir() -> Path:
    raw = os.environ.get("CU_FRAME_DIR")
    path = Path(raw) if raw else Path(__file__).resolve().parent / ".cu-frames"
    path.mkdir(parents=True, exist_ok=True)
    return path


def replay_root() -> Path | None:
    raw = os.environ.get("CU_REPLAY_DIR")
    if raw:
        path = Path(raw)
        return path if path.is_dir() else None
    recordings = Path(__file__).resolve().parents[1] / "agent-runtime" / "recordings"
    return recordings if recordings.is_dir() else None


def _has_media(directory: Path) -> bool:
    try:
        children = list(directory.iterdir())
    except OSError:
        return False
    return any(p.is_file() and (_STILL.search(p.name) or _VIDEO.search(p.name)) for p in children)


def session_dirs() -> list[Path]:
    root = replay_root()
    if root is None:
        return []
    if _has_media(root):
        return [root]
    found = [child for child in root.iterdir() if child.is_dir() and _has_media(child)]
    found.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    return found


def replay_dir() -> Path | None:
    dirs = session_dirs()
    return dirs[0] if dirs else None


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


def _session_dir(session_id: str) -> Path:
    if not _SAFE_NAME.fullmatch(session_id):
        raise HTTPException(400, "invalid session")
    for directory in session_dirs():
        if directory.name == session_id:
            return directory
    raise HTTPException(404, "no replay")


def replay_response(session_id: str, name: str | None = None) -> FileResponse:
    """Serve a still or recording. `name` is required; session_id may be a legacy filename."""
    if name is None:
        directory = replay_dir()
        if directory is None:
            raise HTTPException(404, "no replay")
        path = _safe_file(directory, session_id)
    else:
        path = _safe_file(_session_dir(session_id), name)
    suffix = path.suffix.lower()
    media = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webm": "video/webm",
        ".gif": "image/gif",
        ".mp4": "video/mp4",
    }.get(suffix, "application/octet-stream")
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


def _kind_from_stem(stem: str) -> str:
    lowered = stem.lower()
    if lowered.startswith("playwright"):
        return "playwright"
    if lowered.startswith("computer_use"):
        return "computer_use"
    return "replay"


def _session_label(name: str) -> str:
    match = _SESSION_STAMP.match(name)
    if not match:
        return name
    clock = match.group("time")
    stamp = f"{clock[0:2]}:{clock[2:4]}"
    tag = match.group("tag")
    return f"{stamp} · {tag}" if tag else stamp


def _group_media(directory: Path, session_id: str) -> list[dict]:
    groups: dict[str, dict] = {}
    for path in directory.iterdir():
        if not path.is_file():
            continue
        still = _STILL.search(path.name)
        if still:
            stem = still.group("stem")
            group = groups.setdefault(
                stem,
                {
                    "id": f"{session_id}/{stem}",
                    "stem": stem,
                    "kind": _kind_from_stem(stem),
                    "label": _kind_from_stem(stem).replace("_", " "),
                    "frames": [],
                    "action_frames": [],
                    "recordings": [],
                },
            )
            item = {
                "url": f"/cu/replay/{session_id}/{path.name}",
                "turn": int(still.group("n")),
                "action": f"{still.group('kind')} {int(still.group('n')):02d}",
                "timestamp": None,
                "grant_id": None,
                "source": "replay",
            }
            if still.group("kind").lower() == "frame":
                group["action_frames"].append(item)
            else:
                group["frames"].append(item)
            continue
        video = _VIDEO.search(path.name)
        if video:
            stem = video.group("stem")
            group = groups.setdefault(
                stem,
                {
                    "id": f"{session_id}/{stem}",
                    "stem": stem,
                    "kind": _kind_from_stem(stem),
                    "label": _kind_from_stem(stem).replace("_", " "),
                    "frames": [],
                    "action_frames": [],
                    "recordings": [],
                },
            )
            group["recordings"].append(
                {
                    "url": f"/cu/replay/{session_id}/{path.name}",
                    "name": path.name,
                    "type": video.group("ext").lower(),
                }
            )
    ordered = sorted(groups.values(), key=lambda g: (g["kind"], g["stem"]))
    for group in ordered:
        group["frames"].sort(key=lambda f: f["turn"])
        group["action_frames"].sort(key=lambda f: f["turn"])
        group["recordings"].sort(key=lambda r: r["name"])
    return ordered


def replay_sessions() -> list[dict]:
    sessions: list[dict] = []
    for directory in session_dirs():
        session_id = directory.name
        groups = _group_media(directory, session_id)
        if not groups:
            continue
        sessions.append(
            {
                "id": session_id,
                "label": _session_label(session_id),
                "source": "replay",
                "grant_id": None,
                "groups": groups,
            }
        )
    return sessions


def replay_frames() -> list[dict]:
    sessions = replay_sessions()
    if not sessions:
        return []
    group = sessions[0]["groups"][0]
    return list(group["frames"] or group["action_frames"])


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
    sessions = replay_sessions()
    if live:
        grant_id = next((f["grant_id"] for f in reversed(live) if f.get("grant_id")), None)
        sessions = [
            {
                "id": "live",
                "label": "live",
                "source": "live",
                "grant_id": grant_id,
                "groups": [
                    {
                        "id": "live",
                        "stem": "live",
                        "kind": "live",
                        "label": "live",
                        "frames": live,
                        "action_frames": [],
                        "recordings": [],
                    }
                ],
            },
            *sessions,
        ]
        return {
            "status": "live",
            "grant_id": grant_id,
            "running": session_running(events),
            "frames": live,
            "sessions": sessions,
        }
    if sessions:
        first = sessions[0]["groups"][0]
        return {
            "status": "replay",
            "grant_id": None,
            "running": False,
            "frames": list(first["frames"] or first["action_frames"]),
            "sessions": sessions,
        }
    return {"status": "idle", "grant_id": None, "running": False, "frames": [], "sessions": []}
