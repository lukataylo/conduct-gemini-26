from __future__ import annotations

from typing import Any, Callable

import httpx

from shared.schemas import AuditEvent


def make_emitter(callback_base_url: str, *, client: Any | None = None) -> Callable[[AuditEvent], None]:
    base = callback_base_url.rstrip("/")
    owns_client = client is None
    http = client or httpx.Client(timeout=5.0)

    def emit(event: AuditEvent) -> None:
        url = f"{base}/audit"
        try:
            resp = http.post(url, json=event.model_dump(mode="json"), timeout=5.0)
            resp.raise_for_status()
        except Exception:
            try:
                resp = http.post(url, json=event.model_dump(mode="json"), timeout=5.0)
                resp.raise_for_status()
            except Exception:
                return

    def close() -> None:
        if owns_client:
            http.close()

    emit.close = close  # type: ignore[attr-defined]
    return emit
