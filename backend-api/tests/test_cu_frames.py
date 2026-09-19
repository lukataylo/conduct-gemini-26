import base64

from fastapi.testclient import TestClient
from main import app


JPEG_MIN = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xd9"
)


def test_upload_and_get_frame(tmp_path, monkeypatch):
    monkeypatch.setenv("CU_FRAME_DIR", str(tmp_path))
    monkeypatch.delenv("CU_REPLAY_DIR", raising=False)
    client = TestClient(app)
    resp = client.post(
        "/cu/frames",
        json={
            "grant_id": "g-preview-1",
            "request_id": "r-1",
            "turn": 2,
            "mime": "image/jpeg",
            "data": base64.b64encode(JPEG_MIN).decode("ascii"),
            "action": "click Grant access",
            "mode": "computer_use",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["turn"] == 2
    assert body["screenshot_url"].startswith("/cu/frames/")
    got = client.get(body["screenshot_url"])
    assert got.status_code == 200
    assert got.content == JPEG_MIN
    preview = client.get("/cu/preview").json()
    assert preview["status"] == "live"
    assert preview["frames"][-1]["action"] == "click Grant access"
    assert preview["frames"][-1]["url"] == body["screenshot_url"]
    listed = client.get("/audit").json()
    assert any(
        e["payload"].get("screenshot_url") == body["screenshot_url"] for e in listed
    )


def test_frame_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("CU_FRAME_DIR", str(tmp_path))
    from fastapi import HTTPException
    from cu_frames import _safe_file, frame_dir

    try:
        _safe_file(frame_dir(), "../main.py")
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 400
    client = TestClient(app)
    assert client.get("/cu/frames/nope.jpg").status_code == 404


def test_preview_falls_back_to_replay(tmp_path, monkeypatch):
    frames = tmp_path / "frames"
    replay = tmp_path / "replay"
    frames.mkdir()
    replay.mkdir()
    (replay / "computer_use-demo-turn-01.jpg").write_bytes(JPEG_MIN)
    (replay / "computer_use-demo-turn-03.jpg").write_bytes(JPEG_MIN)
    monkeypatch.setenv("CU_FRAME_DIR", str(frames))
    monkeypatch.setenv("CU_REPLAY_DIR", str(replay))
    from cu_frames import preview

    out = preview([])
    assert out["status"] == "replay"
    assert [f["turn"] for f in out["frames"]] == [1, 3]
    assert out["frames"][0]["url"].startswith("/cu/replay/")
    client = TestClient(app)
    got = client.get(out["frames"][0]["url"])
    assert got.status_code == 200
    assert got.content == JPEG_MIN


def test_preview_idle_when_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("CU_FRAME_DIR", str(tmp_path / "empty-frames"))
    monkeypatch.setenv("CU_REPLAY_DIR", str(tmp_path / "empty-replay"))
    (tmp_path / "empty-frames").mkdir()
    (tmp_path / "empty-replay").mkdir()
    from cu_frames import preview

    assert preview([]) == {"status": "idle", "grant_id": None, "running": False, "frames": []}
