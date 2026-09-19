"""
Executes the *visible* part of the demo: once a Grant is issued, an agent using Gemini
Computer Use actually operates the mock GCP console UI (clicks "Grant access",
types the scope, hits confirm) instead of the backend silently flipping a boolean. This
is the on-stage "wow" moment — the agent is *seen* doing the privileged action, and every
action it takes is logged as an AuditEvent(type=ACTION_EXECUTED).

Keep this isolated from policy-engine: computer-use only ever *executes* a decision
that's already been made (auto-grant or approved-escalation). It never decides.
"""
from __future__ import annotations

import os
import sys
import uuid
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

sys.path.append(str(Path(__file__).resolve().parents[1]))

import audit_logger  # noqa: E402
from shared.schemas import AuditEvent, AuditEventType, Grant  # noqa: E402

MODEL = "gemini-2.5-computer-use-preview-10-2025"
GEMINI_CU_MODEL = MODEL

DEFAULT_CONSOLE_HOSTS = ("127.0.0.1", "localhost")
FAILURE_REASONS = frozenset(
    {
        "turn_budget",
        "blocked",
        "verify_failed",
        "sandbox_error",
        "gemini_unavailable",
        "unknown_host",
    }
)


def grant_goal(grant: Grant) -> str:
    """Instruction for computer-use: enact this grant and no other."""
    expiry = grant.expires_at.date().isoformat()
    return (
        f"Grant access to {grant.resource_id} for principal {grant.requester_id} "
        f"expiring {expiry}. Do not grant any other resource."
    )


def host_allowed(console_url: str, allowlist: list[str] | None = None) -> bool:
    """True when the console URL's hostname is on the allowlist."""
    hosts = allowlist if allowlist is not None else list(DEFAULT_CONSOLE_HOSTS)
    hostname = (urlparse(console_url).hostname or "").lower()
    if not hostname:
        return False
    allowed = {h.lower() for h in hosts}
    return hostname in allowed


class _ActiveGrantScanner(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.entries: list[tuple[str | None, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "li":
            return
        data = dict(attrs)
        self.entries.append((data.get("data-resource"), data.get("data-principal")))


def verify_active(html: str, grant: Grant) -> bool:
    """True when #active-grants HTML lists this grant's resource and principal."""
    scanner = _ActiveGrantScanner()
    scanner.feed(html)
    return any(
        resource == grant.resource_id and principal == grant.requester_id
        for resource, principal in scanner.entries
    )


def completed_event(
    grant: Grant,
    *,
    success: bool,
    reason: str | None,
    actions: list,
    watch_url: str | None,
    mode: str,
    turn_count: int,
) -> AuditEvent:
    """Emit and return the completed ACTION_EXECUTED event for a grant run."""
    if success:
        if reason is not None:
            raise ValueError("reason must be None when success=True")
    elif reason not in FAILURE_REASONS:
        raise ValueError(
            f"reason must be one of {sorted(FAILURE_REASONS)} or None when success=True"
        )

    detail = (
        f"completed grant {grant.resource_id}"
        if success
        else f"grant execution failed: {reason}"
    )
    return audit_logger.log(
        AuditEventType.ACTION_EXECUTED,
        actor="agent",
        detail=detail,
        request_id=grant.request_id,
        grant_id=grant.id,
        payload={
            "phase": "completed",
            "success": success,
            "reason": reason,
            "actions": actions,
            "watch_url": watch_url,
            "mode": mode,
            "turn_count": turn_count,
        },
    )


_VISIBLE_NAMES = {
    "bucket-analytics-raw": "analytics-raw",
    "bq-project-x-finance": "project-x-finance",
    "sql-prod-primary": "prod-primary",
}


class GeminiUnavailableError(RuntimeError):
    """Raised by the live client when GEMINI_API_KEY is missing."""


def _gemini_key_or_none() -> str | None:
    try:
        from envutil import gemini_api_key

        return gemini_api_key()
    except RuntimeError:
        return None


def _page_url(page) -> str:
    url = getattr(page, "url", "") or ""
    return url if isinstance(url, str) else ""


def _effective_safety(safety: str | None, page) -> str:
    resolved = safety or "allowed"
    if resolved == "require_confirmation":
        url = _page_url(page)
        return "allowed" if url and host_allowed(url) else "blocked"
    if resolved == "allowed":
        return "allowed"
    return "blocked"


def _mouse(page):
    mouse = getattr(page, "mouse", None)
    if mouse is None:
        raise AttributeError("page has no mouse")
    return mouse() if callable(mouse) else mouse


def _apply_page_action(page, action: dict) -> None:
    name = action.get("name") or ""
    args = action.get("args") or {}
    if name in {"click", "click_at"}:
        _mouse(page).click(args.get("x", 0), args.get("y", 0))
        return
    if name in {"type", "type_text", "type_text_at"}:
        text = args.get("text") or args.get("value") or ""
        if "x" in args and "y" in args:
            _mouse(page).click(args["x"], args["y"])
        keyboard = getattr(page, "keyboard", None)
        if keyboard is not None:
            keyboard.type(text)
            return
        if hasattr(page, "type"):
            page.type(text)
        return
    if name == "navigate":
        url = args.get("url") or args.get("url_full")
        if url and host_allowed(url):
            page.goto(url)
        return
    if name == "wait":
        delay = args.get("time_ms") or args.get("ms")
        if delay is None and args.get("seconds") is not None:
            delay = int(float(args["seconds"]) * 1000)
        if delay is not None and hasattr(page, "wait_for_timeout"):
            page.wait_for_timeout(int(delay))


def _verify_page(page, grant: Grant) -> bool:
    html = ""
    if hasattr(page, "content"):
        try:
            html = page.content() or ""
        except Exception:
            html = ""
    if not html and hasattr(page, "locator"):
        try:
            html = page.locator("#active-grants").evaluate("el => el.outerHTML")
        except Exception:
            html = ""
    return verify_active(html, grant)


def run_computer_use_loop(grant: Grant, page, client, *, max_turns: int = 20) -> dict:
    """Drive `page` with an injectable Computer Use client. Never calls Gemini itself."""
    goal = grant_goal(grant)
    actions: list[dict] = []
    for turn in range(1, max_turns + 1):
        screenshot = page.screenshot(type="png")
        try:
            action = client.next_action(screenshot, goal)
        except GeminiUnavailableError:
            return {
                "success": False,
                "reason": "gemini_unavailable",
                "actions": actions,
                "turn_count": turn - 1,
            }
        if action is None:
            ok = _verify_page(page, grant)
            return {
                "success": ok,
                "reason": None if ok else "verify_failed",
                "actions": actions,
                "turn_count": turn,
            }
        recorded = {
            "name": action.get("name"),
            "args": action.get("args") or {},
            "intent": action.get("intent"),
            "safety": action.get("safety"),
        }
        if _effective_safety(recorded["safety"], page) == "blocked":
            return {
                "success": False,
                "reason": "blocked",
                "actions": actions,
                "turn_count": turn,
            }
        _apply_page_action(page, recorded)
        actions.append(recorded)
    return {
        "success": False,
        "reason": "turn_budget",
        "actions": actions,
        "turn_count": max_turns,
    }


class GeminiComputerUseClient:
    """Live Gemini Computer Use adapter. Tests inject a mock with `next_action`."""

    def __init__(self, api_key: str | None = None, *, viewport: tuple[int, int] = (1280, 720)):
        self.api_key = api_key if api_key is not None else _gemini_key_or_none()
        self.viewport = viewport
        self._history: list = []
        self._goal_sent = False

    def next_action(self, screenshot_png: bytes, goal: str) -> dict | None:
        if not self.api_key:
            raise GeminiUnavailableError("GEMINI_API_KEY not set")
        from google import genai
        from google.genai import types

        parts = []
        if not self._goal_sent:
            parts.append(types.Part(text=goal))
            self._goal_sent = True
        else:
            parts.append(types.Part(text="Continue from this screenshot."))
        parts.append(types.Part.from_bytes(data=screenshot_png, mime_type="image/png"))
        self._history.append(types.Content(role="user", parts=parts))
        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(
            model=GEMINI_CU_MODEL,
            contents=self._history,
            config=types.GenerateContentConfig(
                tools=[
                    types.Tool(
                        computer_use=types.ComputerUse(
                            environment=types.Environment.ENVIRONMENT_BROWSER,
                        )
                    )
                ]
            ),
        )
        candidate = response.candidates[0] if response.candidates else None
        if candidate is not None and candidate.content is not None:
            self._history.append(candidate.content)
        calls = list(getattr(response, "function_calls", None) or [])
        if not calls and candidate is not None and candidate.content is not None:
            for part in candidate.content.parts or []:
                fc = getattr(part, "function_call", None)
                if fc is not None:
                    calls.append(fc)
        if not calls:
            return None
        return _normalize_cu_action(calls[0], self.viewport)


def _denorm_coord(value, size: int) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0
    if 0 <= numeric <= 999:
        return int(numeric / 999 * size)
    return int(numeric)


def _normalize_cu_action(function_call, viewport: tuple[int, int]) -> dict:
    raw_name = getattr(function_call, "name", None) or "wait"
    args = dict(getattr(function_call, "args", None) or {})
    safety_decision = args.pop("safety_decision", None)
    decision = "allowed"
    if isinstance(safety_decision, dict):
        decision = safety_decision.get("decision") or "allowed"
    elif isinstance(safety_decision, str):
        decision = safety_decision
    if decision in {"block", "blocked", "reject"}:
        safety = "blocked"
    elif decision in {"require_confirmation", "confirm"}:
        safety = "require_confirmation"
    else:
        safety = "allowed"
    name = {
        "click_at": "click",
        "click": "click",
        "type_text_at": "type",
        "type_text": "type",
        "type": "type",
        "navigate": "navigate",
        "wait": "wait",
        "wait_5_seconds": "wait",
    }.get(raw_name, raw_name)
    width, height = viewport
    if name in {"click", "type"} and "x" in args:
        args["x"] = _denorm_coord(args.get("x"), width)
    if name in {"click", "type"} and "y" in args:
        args["y"] = _denorm_coord(args.get("y"), height)
    return {
        "name": name,
        "args": args,
        "intent": args.get("intent") or raw_name,
        "safety": safety,
    }


def execute_grant(
    grant: Grant,
    console_url: str,
    *,
    mode: str | None = None,
    watch_url: str | None = None,
) -> AuditEvent:
    """Drive the mock console to perform `grant`. Playwright is one scripted attempt."""
    resolved = mode or os.environ.get("EXECUTE_GRANT_MODE") or "computer_use"
    if resolved == "playwright":
        return _execute_playwright(grant, console_url, watch_url=watch_url)
    if resolved == "computer_use":
        return _execute_computer_use(grant, console_url, watch_url=watch_url)
    raise ValueError(f"unknown execute mode: {resolved}")


def _execute_computer_use(
    grant: Grant, console_url: str, *, watch_url: str | None
) -> AuditEvent:
    audit_logger.log(
        AuditEventType.ACTION_EXECUTED,
        actor="agent",
        detail=f"started grant {grant.resource_id}",
        request_id=grant.request_id,
        grant_id=grant.id,
        payload={"phase": "started", "mode": "computer_use", "watch_url": watch_url},
    )
    if not host_allowed(console_url):
        return completed_event(
            grant,
            success=False,
            reason="unknown_host",
            actions=[],
            watch_url=watch_url,
            mode="computer_use",
            turn_count=0,
        )
    key = _gemini_key_or_none()
    if not key:
        return completed_event(
            grant,
            success=False,
            reason="gemini_unavailable",
            actions=[],
            watch_url=watch_url,
            mode="computer_use",
            turn_count=0,
        )
    try:
        from playwright.sync_api import sync_playwright

        client = GeminiComputerUseClient(api_key=key)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(console_url)
                result = run_computer_use_loop(grant, page, client)
            finally:
                browser.close()
    except GeminiUnavailableError:
        return completed_event(
            grant,
            success=False,
            reason="gemini_unavailable",
            actions=[],
            watch_url=watch_url,
            mode="computer_use",
            turn_count=0,
        )
    except Exception:
        return completed_event(
            grant,
            success=False,
            reason="sandbox_error",
            actions=[],
            watch_url=watch_url,
            mode="computer_use",
            turn_count=0,
        )
    return completed_event(
        grant,
        success=result["success"],
        reason=result["reason"],
        actions=result["actions"],
        watch_url=watch_url,
        mode="computer_use",
        turn_count=result["turn_count"],
    )


def _execute_playwright(
    grant: Grant, console_url: str, *, watch_url: str | None
) -> AuditEvent:
    audit_logger.log(
        AuditEventType.ACTION_EXECUTED,
        actor="agent",
        detail=f"started grant {grant.resource_id}",
        request_id=grant.request_id,
        grant_id=grant.id,
        payload={"phase": "started", "mode": "playwright", "watch_url": watch_url},
    )
    if not host_allowed(console_url):
        return completed_event(
            grant,
            success=False,
            reason="unknown_host",
            actions=[],
            watch_url=watch_url,
            mode="playwright",
            turn_count=0,
        )

    from playwright.sync_api import sync_playwright

    visible_name = _VISIBLE_NAMES.get(grant.resource_id, grant.resource_id)
    expiry = grant.expires_at.date().isoformat()
    actions = [
        {"intent": f"click Grant access on {visible_name}", "name": "click", "args": {}},
        {"intent": "fill Principal", "name": "type", "args": {"value": grant.requester_id}},
        {"intent": "fill Expires", "name": "type", "args": {"value": expiry}},
        {"intent": "click Confirm", "name": "click", "args": {}},
    ]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(console_url)
            card = page.locator(".card").filter(
                has=page.locator(".name", has_text=visible_name)
            )
            card.get_by_role("button", name="Grant access").click()
            page.get_by_label("Principal").fill(grant.requester_id)
            page.get_by_label("Expires").fill(expiry)
            page.get_by_role("button", name="Confirm").click()
            html = page.locator("#active-grants").evaluate("el => el.outerHTML")
        finally:
            browser.close()

    ok = verify_active(html, grant)
    return completed_event(
        grant,
        success=ok,
        reason=None if ok else "verify_failed",
        actions=actions,
        watch_url=watch_url,
        mode="playwright",
        turn_count=1,
    )


def _action_event(grant: Grant, detail: str, payload: dict | None = None) -> AuditEvent:
    return AuditEvent(
        id=str(uuid.uuid4()),
        type=AuditEventType.ACTION_EXECUTED,
        actor="agent",
        detail=detail,
        grant_id=grant.id,
        request_id=grant.request_id,
        payload=payload or {},
    )
