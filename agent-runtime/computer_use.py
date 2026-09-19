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
import time
import uuid
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

sys.path.append(str(Path(__file__).resolve().parents[1]))

import audit_logger  # noqa: E402
from shared.schemas import AuditEvent, AuditEventType, Grant  # noqa: E402

from gemini_models import DEFAULT_CU_MODEL, computer_use_model, computer_use_thinking  # noqa: E402

MODEL = GEMINI_CU_MODEL = DEFAULT_CU_MODEL
VIEWPORT = (1440, 900)
# google-gemini/computer-use-preview/agent.py
MAX_RECENT_TURN_WITH_SCREENSHOTS = 3
PREDEFINED_COMPUTER_USE_FUNCTIONS = (
    "click",
    "double_click",
    "triple_click",
    "middle_click",
    "right_click",
    "mouse_down",
    "mouse_up",
    "move",
    "type",
    "drag_and_drop",
    "wait",
    "press_key",
    "key_down",
    "key_up",
    "hotkey",
    "take_screenshot",
    "scroll",
    "go_back",
    "navigate",
    "go_forward",
)
LEGACY_PREDEFINED_COMPUTER_USE_FUNCTIONS = (
    "open_web_browser",
    "click_at",
    "hover_at",
    "type_text_at",
    "scroll_document",
    "scroll_at",
    "wait_5_seconds",
    "go_back",
    "go_forward",
    "search",
    "navigate",
    "key_combination",
    "drag_and_drop",
)
_SCREENSHOT_FN_NAMES = frozenset(
    PREDEFINED_COMPUTER_USE_FUNCTIONS + LEGACY_PREDEFINED_COMPUTER_USE_FUNCTIONS
)

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
    visible = _VISIBLE_NAMES.get(grant.resource_id, grant.resource_id)
    return (
        f"Grant access to {grant.resource_id} ({visible}) for principal "
        f"{grant.requester_id} expiring {expiry}. This is a Google Cloud Console. "
        f"Open the matching product in the left nav, open the {visible} resource, "
        f"open the Permissions tab, click Grant access. In the dialog fill "
        f"New principals / Principal with {grant.requester_id}, set Expires to "
        f"{expiry} (YYYY-MM-DD), leave the default role, then click Save "
        f"(aria-label Confirm). Do not grant any other resource."
    )


def revoke_goal(grant: Grant) -> str:
    """Instruction for computer-use: remove this grant and no other."""
    visible = _VISIBLE_NAMES.get(grant.resource_id, grant.resource_id)
    return (
        f"Revoke access to {grant.resource_id} ({visible}) for principal "
        f"{grant.requester_id}. This is a Google Cloud Console. "
        f"Open the matching product in the left nav, open the {visible} resource, "
        f"open the Permissions tab, click Remove for {grant.requester_id}. "
        f"In the dialog click Confirm revoke. "
        f"Do not grant any other resource."
    )


def extra_console_hosts() -> list[str]:
    """Hosts from CONSOLE_ALLOWED_HOSTS plus the hostname of CONSOLE_URL."""
    hosts: list[str] = []
    raw = os.environ.get("CONSOLE_ALLOWED_HOSTS", "")
    hosts.extend(part.strip() for part in raw.split(",") if part.strip())
    console = os.environ.get("CONSOLE_URL")
    if console:
        hostname = urlparse(console).hostname
        if hostname:
            hosts.append(hostname)
    return hosts


def host_allowed(console_url: str, allowlist: list[str] | None = None) -> bool:
    """True when the console URL's hostname is on the allowlist."""
    hosts = (
        allowlist
        if allowlist is not None
        else list(DEFAULT_CONSOLE_HOSTS) + extra_console_hosts()
    )
    hostname = (urlparse(console_url).hostname or "").lower()
    if not hostname:
        return False
    allowed = {h.lower() for h in hosts}
    return hostname in allowed


def current_sandbox_id() -> str:
    return (
        os.environ.get("SANDBOX_ID")
        or os.environ.get("MODAL_TASK_ID")
        or os.environ.get("MODAL_FUNCTION_CALL_ID")
        or "local"
    )


class _ActiveGrantScanner(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.entries: list[tuple[str | None, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"li", "tr"}:
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


def verify_inactive(html: str, grant: Grant) -> bool:
    """True when no data-resource+data-principal pair matches this grant."""
    scanner = _ActiveGrantScanner()
    scanner.feed(html)
    return not any(
        resource == grant.resource_id and principal == grant.requester_id
        for resource, principal in scanner.entries
    )


def recording_dir() -> Path | None:
    """Optional directory for Playwright videos + turn screenshots."""
    raw = os.environ.get("EXECUTE_RECORD_DIR")
    if not raw:
        return None
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _open_recorded_page(playwright, *, stem: str):
    rec = recording_dir()
    slow_raw = os.environ.get("EXECUTE_SLOW_MO")
    if slow_raw is not None:
        slow_mo = int(slow_raw)
    else:
        slow_mo = 350 if rec else 0
    browser = playwright.chromium.launch(headless=True, slow_mo=slow_mo or None)
    context_kwargs: dict = {"viewport": {"width": VIEWPORT[0], "height": VIEWPORT[1]}}
    if rec:
        context_kwargs["record_video_dir"] = str(rec)
        context_kwargs["record_video_size"] = {"width": VIEWPORT[0], "height": VIEWPORT[1]}
    context = browser.new_context(**context_kwargs)
    page = context.new_page()
    return browser, context, page, rec, stem


def _close_recorded_page(browser, context, page, rec: Path | None, stem: str) -> str | None:
    video_path = None
    try:
        video = getattr(page, "video", None)
        page.close()
        context.close()
        if rec is not None and video is not None:
            raw = Path(video.path())
            dest = rec / f"{stem}.webm"
            if raw.exists():
                raw.replace(dest)
                video_path = str(dest)
    finally:
        browser.close()
    return video_path


def frame_publisher(grant: Grant, callback_base_url: str | None, mode: str):
    """POST each turn JPEG to backend-api /cu/frames when a callback origin is set."""
    if not callback_base_url:
        return None

    def on_frame(turn: int, data: bytes, mime: str, action: str | None = None) -> str | None:
        import base64

        from http_emitter import upload_frame

        return upload_frame(
            callback_base_url,
            {
                "grant_id": grant.id,
                "request_id": grant.request_id,
                "turn": turn,
                "mime": mime,
                "data": base64.b64encode(data).decode("ascii"),
                "action": action,
                "mode": mode,
            },
        )

    return on_frame


def emit_turn_frame(
    grant: Grant,
    turn: int,
    screenshot: bytes,
    mime: str,
    *,
    action: str | None = None,
    mode: str = "computer_use",
    on_frame=None,
) -> str | None:
    """Publish a board frame. /cu/frames writes the audit row when upload succeeds."""
    url = None
    if on_frame is not None:
        url = on_frame(turn, screenshot, mime, action)
    if url is None:
        audit_logger.log(
            AuditEventType.ACTION_EXECUTED,
            actor="agent",
            detail=f"turn {turn}" + (f" · {action}" if action else ""),
            request_id=grant.request_id,
            grant_id=grant.id,
            payload={
                "phase": "turn",
                "turn": turn,
                "screenshot_url": url,
                "action": action,
                "mode": mode,
                "status": "ok",
            },
        )
    return url


def completed_event(
    grant: Grant,
    *,
    success: bool,
    reason: str | None,
    actions: list,
    watch_url: str | None,
    mode: str,
    turn_count: int,
    video_path: str | None = None,
    action: str = "grant",
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
            "video_path": video_path,
            "action": action,
        },
    )


_VISIBLE_NAMES = {
    "bucket-analytics-raw": "analytics-raw",
    "bq-project-x-finance": "project-x-finance",
    "sql-prod-primary": "prod-primary",
}

_RESOURCE_NAV = {
    "bucket-analytics-raw": "storage",
    "bq-project-x-finance": "bigquery",
    "sql-prod-primary": "sql",
}


def _open_grant_surface(page, grant: Grant) -> None:
    """Walk the Cloud Console chrome to the resource Permissions tab."""
    nav = _RESOURCE_NAV.get(grant.resource_id)
    if nav:
        nav_btn = page.locator(f'.nav-item[data-nav="{nav}"]')
        _highlight_locator(page, nav_btn)
        nav_btn.click()
    resource = page.locator(f'[data-open-resource="{grant.resource_id}"]:visible')
    _highlight_locator(page, resource)
    resource.click()
    permissions = page.get_by_role("tab", name="Permissions")
    _highlight_locator(page, permissions)
    permissions.click()


class GeminiUnavailableError(RuntimeError):
    """Raised by the live client when GEMINI_API_KEY is missing or Gemini is down."""


def _api_status(exc: Exception) -> int | None:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    text = str(exc)
    for token in (429, 503, 401, 403):
        if str(token) in text:
            return token
    return None


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


def highlight_mouse_enabled() -> bool:
    raw = os.environ.get("EXECUTE_HIGHLIGHT_MOUSE")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return recording_dir() is not None


def highlight_mouse(page, x: float, y: float) -> None:
    """Draw a cursor ring — Playwright video does not capture the OS pointer.

    Same idea as google-gemini/computer-use-preview ``highlight_mouse``.
    """
    if not highlight_mouse_enabled():
        return
    evaluate = getattr(page, "evaluate", None)
    if evaluate is None:
        return
    try:
        evaluate(
            """([x, y]) => {
              let el = document.getElementById("cu-cursor");
              if (!el) {
                el = document.createElement("div");
                el.id = "cu-cursor";
                el.setAttribute("aria-hidden", "true");
                el.style.cssText = [
                  "pointer-events:none",
                  "position:fixed",
                  "z-index:2147483647",
                  "width:24px",
                  "height:24px",
                  "margin-left:-12px",
                  "margin-top:-12px",
                  "border:3px solid #e11d48",
                  "border-radius:50%",
                  "background:rgba(225,29,72,0.28)",
                  "box-shadow:0 0 0 2px #fff, 0 0 10px rgba(225,29,72,0.6)",
                  "box-sizing:border-box",
                ].join(";");
                document.body.appendChild(el);
              }
              el.style.left = x + "px";
              el.style.top = y + "px";
            }""",
            [float(x), float(y)],
        )
    except Exception:
        return
    dwell = int(os.environ.get("EXECUTE_CURSOR_MS", "200"))
    waiter = getattr(page, "wait_for_timeout", None)
    if dwell > 0 and waiter is not None:
        waiter(dwell)


def _highlight_locator(page, locator) -> None:
    box = locator.bounding_box() if hasattr(locator, "bounding_box") else None
    if not box:
        return
    highlight_mouse(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def _mouse(page):
    mouse = getattr(page, "mouse", None)
    if mouse is None:
        raise AttributeError("page has no mouse")
    return mouse() if callable(mouse) else mouse


def _keyboard(page):
    keyboard = getattr(page, "keyboard", None)
    if keyboard is None:
        return None
    return keyboard() if callable(keyboard) else keyboard


def _apply_page_action(page, action: dict) -> None:
    name = action.get("name") or ""
    args = action.get("args") or {}
    mouse = None
    if name in {
        "click",
        "click_at",
        "double_click",
        "triple_click",
        "middle_click",
        "right_click",
        "move",
        "long_press",
        "mouse_down",
        "mouse_up",
        "scroll",
        "hover_at",
        "drag_and_drop",
    }:
        mouse = _mouse(page)
    if name in {"click", "click_at"}:
        highlight_mouse(page, args.get("x", 0), args.get("y", 0))
        mouse.click(args.get("x", 0), args.get("y", 0))
        return
    if name == "double_click":
        highlight_mouse(page, args.get("x", 0), args.get("y", 0))
        mouse.dblclick(args.get("x", 0), args.get("y", 0))
        return
    if name == "right_click":
        highlight_mouse(page, args.get("x", 0), args.get("y", 0))
        mouse.click(args.get("x", 0), args.get("y", 0), button="right")
        return
    if name == "middle_click":
        highlight_mouse(page, args.get("x", 0), args.get("y", 0))
        mouse.click(args.get("x", 0), args.get("y", 0), button="middle")
        return
    if name in {"move", "hover_at"}:
        highlight_mouse(page, args.get("x", 0), args.get("y", 0))
        mouse.move(args.get("x", 0), args.get("y", 0))
        return
    if name in {"type", "type_text", "type_text_at"}:
        text = args.get("text") or args.get("value") or ""
        if "x" in args and "y" in args:
            highlight_mouse(page, args["x"], args["y"])
            _mouse(page).click(args["x"], args["y"])
        keyboard = _keyboard(page)
        if keyboard is not None:
            keyboard.type(text)
            if args.get("press_enter"):
                keyboard.press("Enter")
            return
        if hasattr(page, "type"):
            page.type(text)
        return
    if name == "navigate":
        url = args.get("url") or args.get("url_full")
        if url and host_allowed(url):
            page.goto(url)
        return
    if name == "go_back" and hasattr(page, "go_back"):
        page.go_back()
        return
    if name == "go_forward" and hasattr(page, "go_forward"):
        page.go_forward()
        return
    if name == "scroll":
        dx = dy = 0
        magnitude = int(args.get("magnitude_in_pixels") or args.get("magnitude") or 300)
        direction = (args.get("direction") or "down").lower()
        if direction == "down":
            dy = magnitude
        elif direction == "up":
            dy = -magnitude
        elif direction == "right":
            dx = magnitude
        elif direction == "left":
            dx = -magnitude
        if hasattr(page, "mouse"):
            _mouse(page).wheel(dx, dy)
        return
    if name in {"press_key", "hotkey", "key_combination"}:
        keyboard = _keyboard(page)
        if keyboard is None:
            return
        key = args.get("key") or args.get("keys")
        if isinstance(key, list):
            key = "+".join(str(part) for part in key)
        if key:
            keyboard.press(str(key))
        return
    if name in {"wait", "wait_5_seconds", "take_screenshot", "open_web_browser"}:
        delay = args.get("time_ms") or args.get("ms")
        if delay is None and args.get("seconds") is not None:
            delay = int(float(args["seconds"]) * 1000)
        elif name == "wait_5_seconds":
            delay = 5000
        elif name == "wait" and delay is None:
            delay = 1000
        if delay is not None and hasattr(page, "wait_for_timeout"):
            page.wait_for_timeout(int(delay))
        return


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


def prune_old_screenshots(contents: list, *, keep: int = MAX_RECENT_TURN_WITH_SCREENSHOTS) -> None:
    """Drop screenshot blobs from older user turns (official agent.py)."""
    found = 0
    for content in reversed(contents):
        if getattr(content, "role", None) != "user":
            continue
        parts = getattr(content, "parts", None) or []
        has_screenshot = False
        for part in parts:
            fr = getattr(part, "function_response", None)
            if fr is None:
                continue
            if getattr(fr, "parts", None) and getattr(fr, "name", None) in _SCREENSHOT_FN_NAMES:
                has_screenshot = True
                break
        if not has_screenshot:
            continue
        found += 1
        if found <= keep:
            continue
        for part in parts:
            fr = getattr(part, "function_response", None)
            if fr is not None and getattr(fr, "parts", None):
                fr.parts = None


def capture_screenshot(page) -> tuple[bytes, str]:
    """JPEG by default — smaller uploads per vision turn. PNG via CU_SCREENSHOT_TYPE."""
    kind = (os.environ.get("CU_SCREENSHOT_TYPE") or "jpeg").strip().lower()
    if kind == "png":
        return page.screenshot(type="png"), "image/png"
    quality = int(os.environ.get("CU_SCREENSHOT_QUALITY") or "45")
    try:
        data = page.screenshot(type="jpeg", quality=quality)
    except TypeError:
        data = page.screenshot(type="jpeg")
    return data, "image/jpeg"


def _client_actions(client, screenshot: bytes, goal: str, *, mime_type: str = "image/jpeg"):
    getter = getattr(client, "next_actions", None)
    if getter is not None:
        try:
            return getter(screenshot, goal, mime_type=mime_type)
        except TypeError:
            return getter(screenshot, goal)
    action = client.next_action(screenshot, goal)
    if action is None:
        return None
    return [action]


def run_computer_use_loop(
    grant: Grant,
    page,
    client,
    *,
    max_turns: int = 20,
    record_dir: Path | None = None,
    record_stem: str = "cu",
    on_frame=None,
    mode: str = "computer_use",
) -> dict:
    """Drive `page` with an injectable Computer Use client. Never calls Gemini itself."""
    goal = grant_goal(grant)
    actions: list[dict] = []
    for turn in range(1, max_turns + 1):
        screenshot, mime_type = capture_screenshot(page)
        if record_dir is not None:
            ext = "jpg" if mime_type == "image/jpeg" else "png"
            (record_dir / f"{record_stem}-turn-{turn:02d}.{ext}").write_bytes(screenshot)
        if hasattr(client, "last_url"):
            client.last_url = _page_url(page)
        try:
            batch = _client_actions(client, screenshot, goal, mime_type=mime_type)
        except GeminiUnavailableError:
            return {
                "success": False,
                "reason": "gemini_unavailable",
                "actions": actions,
                "turn_count": turn - 1,
            }
        if batch is None:
            emit_turn_frame(
                grant,
                turn,
                screenshot,
                mime_type,
                action="verify",
                mode=mode,
                on_frame=on_frame,
            )
            ok = _verify_page(page, grant)
            return {
                "success": ok,
                "reason": None if ok else "verify_failed",
                "actions": actions,
                "turn_count": turn,
            }
        for action in batch:
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
        after, after_mime = capture_screenshot(page)
        last = actions[-1] if actions else {}
        label = last.get("intent") or last.get("name")
        emit_turn_frame(
            grant, turn, after, after_mime, action=label, mode=mode, on_frame=on_frame
        )
    return {
        "success": False,
        "reason": "turn_budget",
        "actions": actions,
        "turn_count": max_turns,
    }


class GeminiComputerUseClient:
    """Live client aligned with google-gemini/computer-use-preview/agent.py."""

    def __init__(self, api_key: str | None = None, *, viewport: tuple[int, int] = VIEWPORT):
        self.api_key = api_key if api_key is not None else _gemini_key_or_none()
        self.viewport = viewport
        self.last_url = ""
        self._history: list = []
        self._goal_sent = False
        self._pending: list[tuple[str, str | None, bool]] = []

    def next_action(self, screenshot_png: bytes, goal: str) -> dict | None:
        batch = self.next_actions(screenshot_png, goal)
        if not batch:
            return None
        return batch[0]

    def next_actions(
        self, screenshot_png: bytes, goal: str, *, mime_type: str = "image/jpeg"
    ) -> list[dict] | None:
        if not self.api_key:
            raise GeminiUnavailableError("GEMINI_API_KEY not set")
        from google import genai
        from google.genai import types

        if not self._goal_sent:
            self._history.append(types.Content(role="user", parts=[types.Part(text=goal)]))
            self._goal_sent = True
        else:
            frs = []
            for name, call_id, ack_safety in self._pending:
                extra = {"url": self.last_url}
                if ack_safety:
                    extra["safety_acknowledgement"] = "true"
                kwargs: dict = {
                    "name": name,
                    "response": extra,
                    "parts": [
                        types.FunctionResponsePart(
                            inline_data=types.FunctionResponseBlob(
                                mime_type=mime_type, data=screenshot_png
                            )
                        )
                    ],
                }
                if call_id:
                    kwargs["id"] = call_id
                frs.append(types.FunctionResponse(**kwargs))
            self._pending = []
            if frs:
                self._history.append(
                    types.Content(
                        role="user",
                        parts=[types.Part(function_response=fr) for fr in frs],
                    )
                )
                prune_old_screenshots(self._history)
        client = genai.Client(api_key=self.api_key)
        last_exc: Exception | None = None
        response = None
        model = computer_use_model()
        thinking = computer_use_thinking()
        for attempt in range(5):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=self._history,
                    config=types.GenerateContentConfig(
                        tools=[
                            types.Tool(
                                computer_use=types.ComputerUse(
                                    environment=types.Environment.ENVIRONMENT_BROWSER,
                                )
                            )
                        ],
                        thinking_config=types.ThinkingConfig(
                            thinking_level=thinking,
                            include_thoughts=False,
                        ),
                    ),
                )
                break
            except Exception as exc:
                last_exc = exc
                status = _api_status(exc)
                if status in {429, 503} and attempt < 4:
                    time.sleep(2**attempt)
                    continue
                if status in {401, 403, 429, 503}:
                    raise GeminiUnavailableError(str(exc)) from exc
                raise
        if response is None:
            raise GeminiUnavailableError(str(last_exc) if last_exc else "gemini unavailable")
        candidate = response.candidates[0] if response.candidates else None
        if candidate is not None and candidate.content is not None:
            self._history.append(candidate.content)
        calls = []
        if candidate is not None and candidate.content is not None:
            for part in candidate.content.parts or []:
                fc = getattr(part, "function_call", None)
                if fc is not None:
                    calls.append(fc)
        if not calls:
            calls = list(getattr(response, "function_calls", None) or [])
        if not calls:
            return None
        actions = []
        pending = []
        for call in calls:
            action = _normalize_cu_action(call, self.viewport)
            actions.append(action)
            pending.append(
                (
                    getattr(call, "name", None) or action["name"],
                    getattr(call, "id", None),
                    action.get("safety") == "require_confirmation",
                )
            )
        self._pending = pending
        return actions


def _denorm_coord(value, size: int) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0
    if 0 <= numeric <= 1000:
        return int(numeric / 1000 * size)
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
        "hover_at": "move",
        "key_combination": "hotkey",
    }.get(raw_name, raw_name)
    width, height = viewport
    for axis, size in (("x", width), ("y", height), ("start_x", width), ("start_y", height), ("end_x", width), ("end_y", height)):
        if axis in args:
            args[axis] = _denorm_coord(args.get(axis), size)
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
    callback_base_url: str | None = None,
    action: str = "grant",
) -> AuditEvent:
    """Drive the mock console to perform `grant`. Playwright is one scripted attempt."""
    resolved = mode or os.environ.get("EXECUTE_GRANT_MODE") or "computer_use"
    callback = (callback_base_url or os.environ.get("BACKEND_PUBLIC_URL") or "").strip() or None
    if callback:
        from http_emitter import make_emitter

        audit_logger.set_emitter(make_emitter(callback))
    on_frame = frame_publisher(grant, callback, resolved)
    if action == "revoke" or resolved == "playwright":
        return _execute_playwright(
            grant, console_url, watch_url=watch_url, on_frame=on_frame, action=action
        )
    if resolved == "computer_use":
        return _execute_computer_use(
            grant,
            console_url,
            watch_url=watch_url,
            on_frame=on_frame,
            action=action,
        )
    raise ValueError(f"unknown execute mode: {resolved}")


def _execute_computer_use(
    grant: Grant,
    console_url: str,
    *,
    watch_url: str | None,
    on_frame=None,
    action: str = "grant",
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
            action=action,
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
            action=action,
        )
    try:
        from playwright.sync_api import sync_playwright

        client = GeminiComputerUseClient(api_key=key)
        rec = recording_dir()
        stem = f"computer_use-{grant.resource_id}-{grant.id[:8]}"
        video_path = None
        with sync_playwright() as playwright:
            browser, context, page, rec, stem = _open_recorded_page(playwright, stem=stem)
            try:
                page.goto(console_url)
                result = run_computer_use_loop(
                    grant,
                    page,
                    client,
                    record_dir=rec,
                    record_stem=stem,
                    on_frame=on_frame,
                    mode="computer_use",
                )
            finally:
                video_path = _close_recorded_page(browser, context, page, rec, stem)
    except GeminiUnavailableError:
        return completed_event(
            grant,
            success=False,
            reason="gemini_unavailable",
            actions=[],
            watch_url=watch_url,
            mode="computer_use",
            turn_count=0,
            action=action,
        )
    except Exception as exc:
        print(f"[computer_use] sandbox_error: {type(exc).__name__}: {exc}")
        return completed_event(
            grant,
            success=False,
            reason="sandbox_error",
            actions=[],
            watch_url=watch_url,
            mode="computer_use",
            turn_count=0,
            action=action,
        )
    return completed_event(
        grant,
        success=result["success"],
        reason=result["reason"],
        actions=result["actions"],
        watch_url=watch_url,
        mode="computer_use",
        turn_count=result["turn_count"],
        video_path=video_path,
        action=action,
    )


def _enact_grant_on_page(page, grant: Grant) -> None:
    visible_name = _VISIBLE_NAMES.get(grant.resource_id, grant.resource_id)
    expiry = grant.expires_at.date().isoformat()
    _open_grant_surface(page, grant)
    card = page.locator(".card").filter(has=page.locator(".name", has_text=visible_name))
    grant_btn = card.get_by_role("button", name="Grant access")
    _highlight_locator(page, grant_btn)
    grant_btn.click()
    principal = page.get_by_label("Principal")
    _highlight_locator(page, principal)
    principal.fill(grant.requester_id)
    expires = page.get_by_label("Expires")
    _highlight_locator(page, expires)
    expires.fill(expiry)
    confirm = page.get_by_role("button", name="Confirm")
    _highlight_locator(page, confirm)
    confirm.click()


def _enact_revoke_on_page(page, grant: Grant) -> None:
    _open_grant_surface(page, grant)
    revoke_btn = page.locator(
        f'[data-action="revoke"][data-principal="{grant.requester_id}"]'
    )
    _highlight_locator(page, revoke_btn)
    revoke_btn.click()
    confirm = page.get_by_role("button", name="Confirm revoke")
    _highlight_locator(page, confirm)
    confirm.click()


def _execute_playwright(
    grant: Grant,
    console_url: str,
    *,
    watch_url: str | None,
    on_frame=None,
    action: str = "grant",
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
            action=action,
        )

    from playwright.sync_api import sync_playwright

    visible_name = _VISIBLE_NAMES.get(grant.resource_id, grant.resource_id)
    expiry = grant.expires_at.date().isoformat()
    if action == "revoke":
        actions = [
            {"intent": f"open {visible_name}", "name": "click", "args": {}},
            {"intent": "open Permissions tab", "name": "click", "args": {}},
            {
                "intent": f"click Remove for {grant.requester_id}",
                "name": "click",
                "args": {},
            },
            {"intent": "click Confirm revoke", "name": "click", "args": {}},
        ]
    else:
        actions = [
            {"intent": f"open {visible_name}", "name": "click", "args": {}},
            {"intent": "open Permissions tab", "name": "click", "args": {}},
            {"intent": f"click Grant access on {visible_name}", "name": "click", "args": {}},
            {"intent": "fill Principal", "name": "type", "args": {"value": grant.requester_id}},
            {"intent": "fill Expires", "name": "type", "args": {"value": expiry}},
            {"intent": "click Confirm", "name": "click", "args": {}},
        ]

    rec = recording_dir()
    stem = f"playwright-{grant.resource_id}-{grant.id[:8]}"
    video_path = None
    html = ""
    with sync_playwright() as playwright:
        browser, context, page, rec, stem = _open_recorded_page(playwright, stem=stem)
        try:
            page.goto(console_url)
            first, first_mime = capture_screenshot(page)
            emit_turn_frame(
                grant,
                1,
                first,
                first_mime,
                action="open console",
                mode="playwright",
                on_frame=on_frame,
            )
            if action == "revoke":
                # Mock console state is in-page only; grant first so Remove exists.
                _enact_grant_on_page(page, grant)
                _enact_revoke_on_page(page, grant)
                frame_action = "confirm revoke"
            else:
                _enact_grant_on_page(page, grant)
                frame_action = "confirm grant"
            html = page.locator("#active-grants").evaluate("el => el.outerHTML")
            last, last_mime = capture_screenshot(page)
            emit_turn_frame(
                grant,
                2,
                last,
                last_mime,
                action=frame_action,
                mode="playwright",
                on_frame=on_frame,
            )
        finally:
            video_path = _close_recorded_page(browser, context, page, rec, stem)

    ok = verify_inactive(html, grant) if action == "revoke" else verify_active(html, grant)
    return completed_event(
        grant,
        success=ok,
        reason=None if ok else "verify_failed",
        actions=actions,
        watch_url=watch_url,
        mode="playwright",
        turn_count=1,
        video_path=video_path,
        action=action,
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
