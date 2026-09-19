#!/usr/bin/env python3
"""Record Playwright + Gemini computer-use grants against the mock console."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AR = ROOT / "agent-runtime"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(AR))

from envutil import load_local_env  # noqa: E402

load_local_env()

from computer_use import execute_grant  # noqa: E402
from mock_console.server import serve_in_thread  # noqa: E402
from shared.schemas import Grant  # noqa: E402


def _grant(suffix: str) -> Grant:
    now = datetime.now(timezone.utc)
    return Grant(
        id=f"g-record-{suffix}",
        request_id=f"r-record-{suffix}",
        resource_id="bucket-analytics-raw",
        requester_id="u-newhire-1",
        granted_at=now,
        expires_at=now + timedelta(days=14),
    )


def main() -> int:
    out = Path(os_record_dir())
    out.mkdir(parents=True, exist_ok=True)
    import os

    os.environ["EXECUTE_RECORD_DIR"] = str(out)
    os.environ["EXECUTE_HIGHLIGHT_MOUSE"] = "1"
    os.environ.setdefault("EXECUTE_SLOW_MO", "250")
    os.environ.setdefault("EXECUTE_CURSOR_MS", "220")

    server = serve_in_thread(port=8790)
    results = []
    try:
        for mode in ("playwright", "computer_use"):
            print(f"\n=== recording {mode} ===")
            event = execute_grant(_grant(mode), "http://127.0.0.1:8790/", mode=mode)
            payload = event.payload
            print(json.dumps(
                {
                    "mode": mode,
                    "success": payload.get("success"),
                    "reason": payload.get("reason"),
                    "turns": payload.get("turn_count"),
                    "video_path": payload.get("video_path"),
                    "actions": len(payload.get("actions") or []),
                },
                default=str,
            ))
            results.append((mode, payload))
    finally:
        server.shutdown()

    print("\nrecordings dir:", out)
    return 0 if all(p.get("video_path") for _, p in results) else 1


def os_record_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return AR / "recordings" / stamp


if __name__ == "__main__":
    raise SystemExit(main())
