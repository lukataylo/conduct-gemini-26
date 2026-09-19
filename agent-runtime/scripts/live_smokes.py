#!/usr/bin/env python3
"""Live integration smokes. Requires env.local keys. Not part of pytest."""
from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AR = ROOT / "agent-runtime"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(AR))
sys.path.insert(0, str(ROOT / "backend-api"))

from envutil import gemini_api_key, load_local_env  # noqa: E402

load_local_env()


def _ok(name: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"PASS  {name}{suffix}")


def _fail(name: str, detail: str) -> None:
    print(f"FAIL  {name} — {detail}")


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def smoke_env() -> None:
    _section("env")
    try:
        key = gemini_api_key()
        _ok("gemini_api_key", f"loaded ({len(key)} chars, not printed)")
    except Exception as exc:
        _fail("gemini_api_key", type(exc).__name__)
        raise
    token = os.environ.get("LOGFIRE_TOKEN")
    if token:
        _ok("LOGFIRE_TOKEN", "present")
    else:
        _fail("LOGFIRE_TOKEN", "missing")


def smoke_parse() -> None:
    _section("parse")
    from gemini_parser import parse_request
    from usecase_demo_seed import GOLDEN_PATH_REQUEST_TEXT, REQUESTER, RESOURCES

    known = list(RESOURCES)
    req = parse_request(GOLDEN_PATH_REQUEST_TEXT, REQUESTER, known)
    print("  project:", req.project)
    print("  resource_ids:", req.resource_ids)
    print("  duration_days:", req.requested_duration_days)
    expect = {"bucket-analytics-raw", "bq-project-x-finance"}
    got = set(req.resource_ids)
    if expect <= got and "sql-prod-primary" not in got:
        _ok("parse_request", f"ids={req.resource_ids} project={req.project} days={req.requested_duration_days}")
    else:
        _fail("parse_request", f"ids={req.resource_ids} project={req.project}")


def smoke_summarizer() -> None:
    _section("summarizer")
    from summarizer import summarize_decision
    from shared.schemas import DecisionType, PolicyDecision
    from usecase_demo_seed import REQUESTER, RESOURCES

    decision = PolicyDecision(
        request_id="r-live-1",
        resource_id="bq-project-x-finance",
        decision=DecisionType.ESCALATE,
        reason="Cross-team request (data-platform -> finance) — requires 1 approval(s)",
        required_approver_ids=["u-finance-owner-1", "u-manager-1"],
    )
    text = summarize_decision(decision, RESOURCES["bq-project-x-finance"], REQUESTER)
    print("  summary:", text[:240])
    if text and text != decision.reason and "I need access" not in text:
        _ok("summarize_decision", f"{len(text)} chars")
    else:
        _fail("summarize_decision", "empty, fallback-to-reason, or leaked requester text")


def smoke_a2ui() -> None:
    _section("a2ui")
    from a2ui import CATALOG, _default_runner, compose_ui
    from shared.schemas import EscalationCase, Grant, UIComponentSpec, UISpec

    now = datetime.now(timezone.utc)
    grant = Grant(
        id="g-live-1",
        request_id="r-live-1",
        resource_id="bucket-analytics-raw",
        requester_id="u-newhire-1",
        expires_at=now + timedelta(days=14),
    )
    case = EscalationCase(
        id="c-live-1",
        request_id="r-live-1",
        resource_id="bq-project-x-finance",
        required_approver_ids=["u-manager-1"],
        requester_id="u-newhire-1",
        requested_duration_days=14,
    )
    fallback = compose_ui([grant], [case], "requester", viewer_id="u-newhire-1")
    names = [p.component for p in fallback.panels]
    if "GrantCard" in names and "PendingApprovalCard" in names:
        _ok("compose_ui fallback", f"panels={names}")
    else:
        _fail("compose_ui fallback", f"panels={names}")

    def bad_runner(prompt: str) -> UISpec:
        return UISpec(
            requester_id="u-newhire-1",
            panels=[
                UIComponentSpec(id="x", component="EvilWidget", props={"grant_id": "g-live-1"}),
                UIComponentSpec(
                    id="grant-g-live-1",
                    component="GrantCard",
                    props={"grant_id": "g-live-1", "resource_id": "bucket-analytics-raw"},
                ),
            ],
        )

    dropped = compose_ui([grant], [], "requester", viewer_id="u-newhire-1", runner=bad_runner)
    if all(p.component in CATALOG for p in dropped.panels) and all(
        p.component != "EvilWidget" for p in dropped.panels
    ):
        _ok("compose_ui drops off-catalog", f"panels={[p.component for p in dropped.panels]}")
    else:
        _fail("compose_ui drops off-catalog", str([p.component for p in dropped.panels]))

    try:
        raw_live = _default_runner(
            "Role: requester\nViewer: u-newhire-1\n"
            "Catalog: GrantCard, PendingApprovalCard, AuditTimeline, ConsoleWatchCard\n"
            f"Grants: {[grant.model_dump(mode='json')]}\n"
            f"Cases: {[case.model_dump(mode='json')]}\n"
        )
        live = compose_ui(
            [grant], [case], "requester", viewer_id="u-newhire-1", runner=lambda _p: raw_live
        )
        live_names = [p.component for p in live.panels]
        if all(p.component in CATALOG for p in live.panels) and live.panels:
            _ok("compose_ui live Gemini", f"panels={live_names}")
        else:
            _fail("compose_ui live Gemini", f"panels={live_names}")
    except Exception as exc:
        _fail("compose_ui live Gemini", f"{type(exc).__name__}: {exc}")
    print("  note: compose_ui(runner=None) is deterministic fallback, not Gemini")


def smoke_allowlist() -> None:
    _section("host allowlist")
    from computer_use import host_allowed

    if host_allowed("http://127.0.0.1:8765/") and host_allowed("http://localhost:8765/"):
        _ok("host_allowed localhost")
    else:
        _fail("host_allowed localhost", "127.0.0.1/localhost rejected")
    if not host_allowed("https://evil.example/") and not host_allowed(
        "https://access-scope-agent-runtime-something.modal.run/"
    ):
        _ok("host_allowed rejects public/modal hosts")
    else:
        _fail("host_allowed rejects public", "unexpected allow")


def _grant() -> object:
    from shared.schemas import Grant

    now = datetime.now(timezone.utc)
    return Grant(
        id="g-live-exec",
        request_id="r-live-exec",
        resource_id="bucket-analytics-raw",
        requester_id="u-newhire-1",
        granted_at=now,
        expires_at=now + timedelta(days=14),
    )


def smoke_playwright() -> None:
    _section("playwright execute")
    import audit_logger
    from computer_use import execute_grant
    from mock_console.server import serve_in_thread

    audit_logger.reset()
    server = serve_in_thread(port=8765)
    try:
        event = execute_grant(_grant(), "http://127.0.0.1:8765/", mode="playwright")
        payload = event.payload
        phases = [e.payload.get("phase") for e in audit_logger.local_events()]
        ok = (
            payload.get("phase") == "completed"
            and payload.get("success") is True
            and payload.get("mode") == "playwright"
            and "started" in phases
            and event.actor == "agent"
        )
        if ok:
            _ok("playwright execute", f"actions={len(payload.get('actions') or [])}")
        else:
            _fail("playwright execute", json.dumps(payload, default=str))
    finally:
        server.shutdown()


def smoke_computer_use() -> None:
    _section("gemini computer_use")
    import audit_logger
    from computer_use import execute_grant
    from mock_console.server import serve_in_thread

    audit_logger.reset()
    server = serve_in_thread(port=8766)
    try:
        event = execute_grant(_grant(), "http://127.0.0.1:8766/", mode="computer_use")
        payload = event.payload
        print("  cu payload:", json.dumps({k: payload.get(k) for k in ("phase", "success", "reason", "mode", "turn_count")}, default=str))
        print("  actions:", len(payload.get("actions") or []))
        if payload.get("phase") == "completed" and payload.get("success") is True:
            _ok("computer_use execute")
        elif payload.get("reason") in {
            "turn_budget",
            "blocked",
            "verify_failed",
            "sandbox_error",
            "gemini_unavailable",
            "unknown_host",
        }:
            _fail(
                "computer_use execute",
                f"closed failure reason={payload.get('reason')} turns={payload.get('turn_count')}",
            )
        else:
            _fail("computer_use execute", json.dumps(payload, default=str))
    finally:
        server.shutdown()


def _start_backend(port: int = 8010):
    import uvicorn
    from main import app

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="backend-api")
    thread.start()
    import time

    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    return server


def smoke_audit_and_emitter() -> None:
    _section("POST /audit + emitter")
    import httpx
    import audit_logger
    from computer_use import execute_grant
    from http_emitter import make_emitter
    from mock_console.server import serve_in_thread

    port = 8010
    _start_backend(port)
    base = f"http://127.0.0.1:{port}"
    client = httpx.Client(timeout=10.0)
    fake = client.post(
        f"{base}/audit",
        json={
            "id": "client-supplied-ignored",
            "type": "action_executed",
            "actor": "agent",
            "detail": "live smoke ACTION_EXECUTED",
            "request_id": "r-live-audit",
            "grant_id": "g-live-audit",
            "payload": {"phase": "completed", "success": True, "mode": "smoke"},
        },
    )
    verify = client.get(f"{base}/audit/verify")
    if fake.status_code == 200 and verify.status_code == 200 and verify.json().get("ok") is True:
        _ok("POST /audit + GET /audit/verify", f"length={verify.json().get('length')}")
    else:
        _fail("POST /audit + verify", f"{fake.status_code} {verify.status_code} {verify.text}")

    audit_logger.reset()
    audit_logger.set_emitter(make_emitter(base, client=client))
    server = serve_in_thread(port=8767)
    try:
        event = execute_grant(_grant(), "http://127.0.0.1:8767/", mode="playwright")
        listed = client.get(f"{base}/audit").json()
        found = [
            e
            for e in listed
            if e.get("type") == "action_executed"
            and e.get("grant_id") == event.grant_id
            and (e.get("payload") or {}).get("phase") == "completed"
        ]
        if found:
            _ok("emitter -> GET /audit", f"events={len(found)}")
        else:
            _fail("emitter -> GET /audit", f"no ACTION_EXECUTED for {event.grant_id}")
    finally:
        server.shutdown()
        client.close()


def _load_seed() -> None:
    import importlib.util

    path = ROOT / "usecase-demo" / "seed_data.py"
    spec = importlib.util.spec_from_file_location("usecase_demo_seed", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["usecase_demo_seed"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]


def main() -> int:
    print("live smokes (secrets not printed)")
    failures = 0
    _load_seed()
    steps = [
        smoke_env,
        smoke_parse,
        smoke_summarizer,
        smoke_a2ui,
        smoke_allowlist,
        smoke_playwright,
        smoke_computer_use,
        smoke_audit_and_emitter,
    ]
    for step in steps:
        try:
            step()
        except Exception as exc:
            failures += 1
            _fail(step.__name__, f"{type(exc).__name__}: {exc}")
            traceback.print_exc()
    print("\n=== done ===")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
