from __future__ import annotations

import os
from pathlib import Path


def load_local_env(path: Path | None = None) -> None:
    """Load KEY=VALUE lines into os.environ if the key is not already set."""
    candidates = []
    if path is not None:
        candidates.append(path)
    else:
        here = Path(__file__).resolve()
        repo = here.parents[1]
        candidates.extend([repo / "env.local", repo / ".env", here.parent / "env.local"])
    for candidate in candidates:
        if not candidate.is_file():
            continue
        for raw in candidate.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
        break


def gemini_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINIAPIKEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    return key
