# Agent Runtime Core (Parse + Computer Use) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship track 2 core: Gemini-parsed `AccessRequest`s, Gemini Computer Use that executes an already-issued `Grant` on a mock console, and A2UI `compose_ui` so track 1 can render a generated spec.

**Architecture:** `parse_request` is the only place free text becomes an `AccessRequest`. `execute_grant` never decides access; it drives Playwright (and optionally Gemini Computer Use vision) against a mock console and emits `ACTION_EXECUTED` events. `compose_ui` emits an A2UI-shaped `UISpec` against a fixed catalog. Modal exposes parse, execute, and compose. Backend stays the only writer of grants.

**Tech Stack:** Python 3.12, Pydantic v2, Pydantic AI, Logfire, google-genai ≥ 1.0, Playwright, Modal, pytest. Shared models from `shared/schemas.py`.

## Global Constraints

- LLMs never grant access. Parse → policy-engine → Grant. Computer use only executes an existing Grant.
- Resource ids in parse output must be a subset of `known_resource_ids`. Unknown names are dropped, never invented.
- `GEMINI_API_KEY` is required; also accept alias `GEMINIAPIKEY` from `env.local`.
- Logfire: `logfire.configure(send_to_logfire="if-token-present")` and `logfire.instrument_pydantic_ai()`. Never require `LOGFIRE_TOKEN` for tests.
- Computer use default mode is `computer_use`. `EXECUTE_GRANT_MODE=playwright` is the reliability path (typed clicks, no vision).
- `execute_grant` does not revoke or create grants. Failure emits `ACTION_EXECUTED` with `payload.success=false`.
- Closed failure reasons: `turn_budget`, `blocked`, `verify_failed`, `sandbox_error`, `gemini_unavailable`, `unknown_host`.
- Actor on computer-use audit events is always `"agent"`. Type is always `AuditEventType.ACTION_EXECUTED`.
- `payload.phase` is `"started"` then `"completed"`.
- Do not add Anthropic computer use. Do not add Jev. Do not add the scoped MCP server in this plan. A2UI `compose_ui` is in scope (Task 11).
- Do not commit `env.local`, `.env`, or any API keys.
- Tests must not call the live Gemini API. Mock the model client.
- Repo root must be on `sys.path` (existing pattern in each module).
- Work only under `agent-runtime/` plus a minimal `POST /audit` on `backend-api/main.py`. Do not rewrite policy-engine or generative-ui.

## File map

- Create: `agent-runtime/envutil.py` — load `env.local` / `.env`, resolve Gemini key
- Create: `agent-runtime/summarizer.py` — `summarize_decision(...)`
- Create: `agent-runtime/a2ui.py` — `compose_ui(...)` + `CATALOG`
- Create: `agent-runtime/http_emitter.py` — POST AuditEvent to `{callback}/audit`
- Create: `agent-runtime/mock_console/index.html` — Grant access UI
- Create: `agent-runtime/mock_console/server.py` — tiny local static server
- Create: `agent-runtime/tests/conftest.py` — fixtures (requester, grant, reset audit)
- Create: `agent-runtime/tests/test_envutil.py`
- Create: `agent-runtime/tests/test_parser.py`
- Create: `agent-runtime/tests/test_summarizer.py`
- Create: `agent-runtime/tests/test_audit_logger.py`
- Create: `agent-runtime/tests/test_computer_use.py`
- Create: `agent-runtime/tests/test_http_emitter.py`
- Create: `agent-runtime/tests/test_a2ui.py`
- Modify: `agent-runtime/requirements.txt`
- Modify: `agent-runtime/audit_logger.py` — `trace_id`, `reset()`
- Modify: `agent-runtime/gemini_parser.py` — real parse path with injectable runner
- Modify: `agent-runtime/computer_use.py` — Playwright + Gemini CU loop
- Modify: `agent-runtime/modal_app.py` — wire endpoints
- Modify: `backend-api/main.py` — add `POST /audit`

---

### Task 1: Env helper and dependencies

**Files:**
- Create: `agent-runtime/envutil.py`
- Create: `agent-runtime/tests/test_envutil.py`
- Modify: `agent-runtime/requirements.txt`

**Interfaces:**
- Consumes: nothing
- Produces: `load_local_env(path: Path | None = None) -> None`, `gemini_api_key() -> str`

- [ ] **Step 1: Write the failing test**

Create `agent-runtime/tests/test_envutil.py`:

```python
from pathlib import Path

from envutil import gemini_api_key, load_local_env


def test_gemini_api_key_reads_standard_name(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINIAPIKEY", raising=False)
    env = tmp_path / "env.local"
    env.write_text("GEMINI_API_KEY=abc123\n")
    load_local_env(env)
    assert gemini_api_key() == "abc123"


def test_gemini_api_key_accepts_alias(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINIAPIKEY", raising=False)
    env = tmp_path / "env.local"
    env.write_text("GEMINIAPIKEY=alias-key\n")
    load_local_env(env)
    assert gemini_api_key() == "alias-key"


def test_gemini_api_key_missing_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINIAPIKEY", raising=False)
    try:
        gemini_api_key()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "GEMINI_API_KEY" in str(exc)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_envutil.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'envutil'`

- [ ] **Step 3: Write minimal implementation**

Replace `agent-runtime/requirements.txt` with:

```
pydantic>=2.6
pydantic-ai>=0.7
logfire>=3.0
google-genai>=1.0
playwright>=1.49
httpx>=0.27
modal>=0.64
fastapi>=0.110
pytest>=8.0
```

Create `agent-runtime/envutil.py`:

```python
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
```

- [ ] **Step 4: Run tests and make sure they pass**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_envutil.py -v`

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add agent-runtime/envutil.py agent-runtime/tests/test_envutil.py agent-runtime/requirements.txt
git commit -m "$(cat <<'EOF'
Add env loader that accepts GEMINI_API_KEY or GEMINIAPIKEY.

EOF
)"
```

---

### Task 2: Audit logger trace_id, reset, HTTP emitter

**Files:**
- Modify: `agent-runtime/audit_logger.py`
- Create: `agent-runtime/http_emitter.py`
- Create: `agent-runtime/tests/test_audit_logger.py`
- Create: `agent-runtime/tests/test_http_emitter.py`
- Create: `agent-runtime/tests/conftest.py`

**Interfaces:**
- Consumes: `shared.schemas.AuditEvent`, `AuditEventType`
- Produces: `audit_logger.log(..., trace_id: str | None = None)`, `audit_logger.reset() -> None`, `http_emitter.make_emitter(callback_base_url: str) -> Callable[[AuditEvent], None]`

- [ ] **Step 1: Write the failing tests**

Create `agent-runtime/tests/conftest.py`:

```python
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))
sys.path.append(str(ROOT / "agent-runtime"))

from shared.schemas import Grant, Requester  # noqa: E402


@pytest.fixture
def requester() -> Requester:
    return Requester(
        id="u-newhire-1",
        name="Alex Chen",
        role="Software Engineer (new hire)",
        team="data-platform",
        manager_id="u-manager-1",
    )


@pytest.fixture
def grant() -> Grant:
    now = datetime.now(timezone.utc)
    return Grant(
        id="g-1",
        request_id="r-1",
        resource_id="bucket-analytics-raw",
        requester_id="u-newhire-1",
        granted_at=now,
        expires_at=now + timedelta(days=14),
    )
```

Create `agent-runtime/tests/test_audit_logger.py`:

```python
from audit_logger import local_events, log, reset, set_emitter
from shared.schemas import AuditEventType


def test_log_includes_trace_id():
    reset()
    event = log(
        AuditEventType.ACTION_EXECUTED,
        actor="agent",
        detail="started",
        request_id="r-1",
        grant_id="g-1",
        trace_id="trace-abc",
        payload={"phase": "started"},
    )
    assert event.trace_id == "trace-abc"
    assert local_events()[0].trace_id == "trace-abc"


def test_reset_clears_sink_and_emitter():
    seen = []
    set_emitter(seen.append)
    log(AuditEventType.ACTION_EXECUTED, actor="agent", detail="x")
    reset()
    assert local_events() == []
    log(AuditEventType.ACTION_EXECUTED, actor="agent", detail="y")
    assert seen == []  # emitter cleared
```

Create `agent-runtime/tests/test_http_emitter.py`:

```python
from http_emitter import make_emitter
from shared.schemas import AuditEvent, AuditEventType


class FakeClient:
    def __init__(self):
        self.calls = []

    def post(self, url, json, timeout):
        self.calls.append((url, json, timeout))

        class Resp:
            def raise_for_status(self):
                return None

        return Resp()


def test_emitter_posts_audit_event():
    client = FakeClient()
    emit = make_emitter("http://backend.example.com", client=client)
    event = AuditEvent(
        id="evt-1",
        type=AuditEventType.ACTION_EXECUTED,
        actor="agent",
        detail="started",
        grant_id="g-1",
        request_id="r-1",
        payload={"phase": "started"},
    )
    emit(event)
    assert client.calls[0][0] == "http://backend.example.com/audit"
    assert client.calls[0][1]["id"] == "evt-1"
    assert client.calls[0][1]["type"] == "action_executed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_audit_logger.py tests/test_http_emitter.py -v`

Expected: FAIL (`reset` missing and/or `make_emitter` missing)

- [ ] **Step 3: Write minimal implementation**

Update `audit_logger.log` to accept `trace_id: str | None = None` and pass it into `AuditEvent`. Add:

```python
def reset() -> None:
    global _emit
    _sink.clear()
    _emit = None
```

Create `agent-runtime/http_emitter.py`:

```python
from __future__ import annotations

from typing import Any, Callable

import httpx

from shared.schemas import AuditEvent


def make_emitter(callback_base_url: str, *, client: Any | None = None) -> Callable[[AuditEvent], None]:
    base = callback_base_url.rstrip("/")
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

    return emit
```

- [ ] **Step 4: Run tests and make sure they pass**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_audit_logger.py tests/test_http_emitter.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-runtime/audit_logger.py agent-runtime/http_emitter.py agent-runtime/tests
git commit -m "$(cat <<'EOF'
Add audit reset, trace_id, and HTTP emitter for Modal callbacks.

EOF
)"
```

---

### Task 3: Parse helpers — duration, constrain ids, build request

**Files:**
- Modify: `agent-runtime/gemini_parser.py`
- Create: `agent-runtime/tests/test_parser.py`

**Interfaces:**
- Consumes: `AccessRequest`, `Requester`, `_build_request` (already in file)
- Produces: `constrain_resource_ids(ids: list[str], known: list[str]) -> list[str]`, `duration_days(raw_text: str, parsed_days: int | None, *, today=None) -> int`, `ParseFields` model

- [ ] **Step 1: Write the failing tests** (append to `test_parser.py`)

```python
from datetime import date

from gemini_parser import constrain_resource_ids, duration_days, _build_request
from shared.schemas import Requester

ALEX = Requester(
    id="u-newhire-1",
    name="Alex Chen",
    role="SE",
    team="data-platform",
    manager_id="u-manager-1",
)
KNOWN = ["bucket-analytics-raw", "bq-project-x-finance", "sql-prod-primary"]


def test_constrain_drops_unknown_preserves_order():
    assert constrain_resource_ids(
        ["bq-project-x-finance", "not-a-thing", "bucket-analytics-raw"],
        KNOWN,
    ) == ["bq-project-x-finance", "bucket-analytics-raw"]


def test_constrain_dedupes():
    assert constrain_resource_ids(["bucket-analytics-raw", "bucket-analytics-raw"], KNOWN) == [
        "bucket-analytics-raw"
    ]


def test_duration_defaults_to_14():
    assert duration_days("I need the analytics-raw bucket", None) == 14


def test_duration_uses_parsed_value():
    assert duration_days("need access", 30) == 30


def test_duration_from_done_by_date():
    assert duration_days(
        "done by Nov 15",
        None,
        today=date(2026, 9, 19),
    ) == (date(2026, 11, 15) - date(2026, 9, 19)).days


def test_duration_minimum_one_day():
    assert duration_days("done by Sep 1", None, today=date(2026, 9, 19)) == 1


def test_build_request_keeps_raw_text(requester):
    req = _build_request(
        raw_text="I need analytics-raw for Project Atlas",
        requester=requester,
        project="atlas-migration",
        resource_ids=["bucket-analytics-raw"],
        requested_duration_days=14,
    )
    assert req.raw_text == "I need analytics-raw for Project Atlas"
    assert req.task_description == req.raw_text
    assert req.resource_ids == ["bucket-analytics-raw"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_parser.py -v`

Expected: FAIL — `constrain_resource_ids` / `duration_days` not defined

- [ ] **Step 3: Write minimal implementation**

Add to `gemini_parser.py` (keep existing `PARSE_PROMPT` and `_build_request`):

```python
from datetime import date, datetime
import re
from pydantic import BaseModel, Field


class ParseFields(BaseModel):
    project: str = "atlas-migration"
    resource_ids: list[str] = Field(default_factory=list)
    requested_duration_days: int | None = None


def constrain_resource_ids(ids: list[str], known: list[str]) -> list[str]:
    known_set = set(known)
    out: list[str] = []
    for item in ids:
        if item in known_set and item not in out:
            out.append(item)
    return out


def duration_days(raw_text: str, parsed_days: int | None, *, today: date | None = None) -> int:
    if parsed_days is not None and parsed_days > 0:
        return parsed_days
    today = today or date.today()
    match = re.search(
        r"done by\s+([A-Za-z]{3,9}\s+\d{1,2}(?:,\s*\d{4})?)",
        raw_text,
        flags=re.IGNORECASE,
    )
    if match:
        text = match.group(1)
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d", "%B %d"):
            try:
                parsed = datetime.strptime(text, fmt)
                year = parsed.year if "%Y" in fmt else today.year
                target = date(year, parsed.month, parsed.day)
                return max(1, (target - today).days)
            except ValueError:
                continue
    return 14
```

- [ ] **Step 4: Run tests and make sure they pass**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_parser.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-runtime/gemini_parser.py agent-runtime/tests/test_parser.py
git commit -m "$(cat <<'EOF'
Add parse helpers that constrain resource ids and infer duration.

EOF
)"
```

---

### Task 4: `parse_request` with injectable runner (no live Gemini)

**Files:**
- Modify: `agent-runtime/gemini_parser.py`
- Modify: `agent-runtime/tests/test_parser.py`

**Interfaces:**
- Consumes: `ParseFields`, `constrain_resource_ids`, `duration_days`, `_build_request`, `gemini_api_key`
- Produces: `parse_request(raw_text, requester, known_resource_ids, *, runner=None) -> AccessRequest` where `runner(prompt: str) -> ParseFields`

- [ ] **Step 1: Write the failing tests**

Append:

```python
from gemini_parser import ParseFields, parse_request


def test_parse_request_uses_runner_and_drops_unknown(requester):
    def runner(prompt: str) -> ParseFields:
        assert "bucket-analytics-raw" in prompt
        assert "I need access" in prompt
        return ParseFields(
            project="atlas-migration",
            resource_ids=["bucket-analytics-raw", "totally-fake"],
            requested_duration_days=14,
        )

    req = parse_request(
        "I need access to analytics-raw for Project Atlas",
        requester,
        ["bucket-analytics-raw", "bq-project-x-finance"],
        runner=runner,
    )
    assert req.resource_ids == ["bucket-analytics-raw"]
    assert req.project == "atlas-migration"
    assert req.requested_duration_days == 14
    assert req.requester.id == "u-newhire-1"


def test_parse_request_empty_ids_when_nothing_matches(requester):
    def runner(prompt: str) -> ParseFields:
        return ParseFields(project="x", resource_ids=["nope"], requested_duration_days=7)

    req = parse_request("please give me prod", requester, ["bucket-analytics-raw"], runner=runner)
    assert req.resource_ids == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_parser.py::test_parse_request_uses_runner_and_drops_unknown -v`

Expected: FAIL — `parse_request` still raises `NotImplementedError` or rejects `runner`

- [ ] **Step 3: Write minimal implementation**

Replace `parse_request` so that:

1. If `runner` is None, build a default runner that uses a Pydantic AI `Agent` with `output_type=ParseFields`, model `google-gla:gemini-2.5-flash`, `gemini_api_key()` as `GOOGLE_API_KEY`/`GEMINI_API_KEY` in env. Wrap with `logfire.configure(send_to_logfire="if-token-present")` and `logfire.instrument_pydantic_ai()` once (guard with a module-level `_LOGFIRE_READY` flag). The default runner is unused by unit tests.
2. If `runner` is provided, call it with a prompt that includes `PARSE_PROMPT`, the joined `known_resource_ids`, and `raw_text`.
3. Constrain ids, compute duration, return `_build_request(...)`.

Do not call Gemini inside tests.

Default runner sketch (only used when `runner is None`):

```python
def _default_runner(prompt: str) -> ParseFields:
    from pydantic_ai import Agent

    _ensure_logfire()
    agent = Agent("google-gla:gemini-2.5-flash", output_type=ParseFields, system_prompt=PARSE_PROMPT)
    result = agent.run_sync(prompt)
    return result.output
```

- [ ] **Step 4: Run tests and make sure they pass**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_parser.py -v`

Expected: PASS (all parser tests, no network)

- [ ] **Step 5: Commit**

```bash
git add agent-runtime/gemini_parser.py agent-runtime/tests/test_parser.py
git commit -m "$(cat <<'EOF'
Wire parse_request to an injectable structured runner.

EOF
)"
```

---

### Task 5: Approver summary from typed PolicyDecision

**Files:**
- Create: `agent-runtime/summarizer.py`
- Create: `agent-runtime/tests/test_summarizer.py`

**Interfaces:**
- Consumes: `PolicyDecision`, `Resource`, `Requester`
- Produces: `summarize_decision(decision: PolicyDecision, resource: Resource, requester: Requester, *, runner=None) -> str`

- [ ] **Step 1: Write the failing tests**

```python
from summarizer import summarize_decision
from shared.schemas import DecisionType, PolicyDecision, Resource, ResourceType, SensitivityTier


def test_summarize_uses_runner_not_raw_requester_text(requester):
    decision = PolicyDecision(
        request_id="r-1",
        resource_id="bq-project-x-finance",
        decision=DecisionType.ESCALATE,
        reason="Cross-team request (data-platform -> finance) — requires 1 approval(s)",
        required_approver_ids=["u-finance-owner-1", "u-manager-1"],
    )
    resource = Resource(
        id="bq-project-x-finance",
        name="project-x-finance",
        type=ResourceType.BIGQUERY_DATASET,
        owning_team="finance",
        sensitivity=SensitivityTier.RESTRICTED,
        project="atlas-migration",
    )

    def runner(prompt: str) -> str:
        assert "I need" not in prompt  # never the requester's raw pitch
        assert "Cross-team request" in prompt
        assert "project-x-finance" in prompt
        return "Alex (data-platform) needs the finance dataset; policy escalated because it is cross-team."

    text = summarize_decision(decision, resource, requester, runner=runner)
    assert "cross-team" in text.lower()


def test_summarize_fallback_is_reason_string(requester):
    decision = PolicyDecision(
        request_id="r-1",
        resource_id="bucket-analytics-raw",
        decision=DecisionType.AUTO_GRANT,
        reason="internal tier, 14d within 30d limit, same-team requester",
    )
    resource = Resource(
        id="bucket-analytics-raw",
        name="analytics-raw",
        type=ResourceType.GCS_BUCKET,
        owning_team="data-platform",
        sensitivity=SensitivityTier.INTERNAL,
        project="atlas-migration",
    )
    assert summarize_decision(decision, resource, requester, runner=lambda p: (_ for _ in ()).throw(RuntimeError("boom"))) == decision.reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_summarizer.py -v`

Expected: FAIL — module missing

- [ ] **Step 3: Write minimal implementation**

`summarizer.py` builds a prompt from `decision.reason`, `decision.decision`, `resource.name`, `resource.sensitivity`, `resource.owning_team`, `requester.name`, `requester.team` only. If `runner` raises or returns blank, return `decision.reason`. Default runner (live) uses a Pydantic AI agent with `output_type=str` and the same Logfire setup.

- [ ] **Step 4: Run tests and make sure they pass**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_summarizer.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-runtime/summarizer.py agent-runtime/tests/test_summarizer.py
git commit -m "$(cat <<'EOF'
Add decision summaries that only see typed policy output.

EOF
)"
```

---

### Task 6: Mock GCP console page

**Files:**
- Create: `agent-runtime/mock_console/index.html`
- Create: `agent-runtime/mock_console/server.py`

**Interfaces:**
- Consumes: seed resource display names `analytics-raw`, `project-x-finance`, `prod-primary`
- Produces: a page with labels **Grant access**, **Principal**, **Expires**, **Confirm**, **Active grants**. After confirm, an `#active-grants` list item with `data-resource` and `data-principal`.

- [ ] **Step 1: Write the failing test**

Create `agent-runtime/tests/test_mock_console.py`:

```python
from pathlib import Path

HTML = Path(__file__).resolve().parents[1] / "mock_console" / "index.html"


def test_console_has_required_labels():
    text = HTML.read_text()
    for label in ("Grant access", "Principal", "Expires", "Confirm", "Active grants"):
        assert label in text
    for name in ("analytics-raw", "project-x-finance", "prod-primary"):
        assert name in text
    assert 'id="active-grants"' in text
    assert "data-resource" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_mock_console.py -v`

Expected: FAIL — file missing

- [ ] **Step 3: Write the page and server**

`index.html` is a single self-contained file (inline CSS/JS). Three resource cards. Clicking **Grant access** on a card reveals Principal + Expires + Confirm. Confirm appends:

```html
<li data-resource="bucket-analytics-raw" data-principal="u-newhire-1">...</li>
```

Map display name → id:

- analytics-raw → `bucket-analytics-raw`
- project-x-finance → `bq-project-x-finance`
- prod-primary → `sql-prod-primary`

`server.py`:

```python
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main(host: str = "127.0.0.1", port: int = 8765) -> None:
    os_cwd = Path(__file__).resolve().parent
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(os_cwd), **kwargs)

    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests and make sure they pass**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_mock_console.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-runtime/mock_console agent-runtime/tests/test_mock_console.py
git commit -m "$(cat <<'EOF'
Add a stub mock console so computer use is not blocked on track 4.

EOF
)"
```

---

### Task 7: Computer-use goal, verify, and completed event (no browser)

**Files:**
- Modify: `agent-runtime/computer_use.py`
- Create: `agent-runtime/tests/test_computer_use.py`

**Interfaces:**
- Consumes: `Grant`, `AuditEvent`, `audit_logger.log`
- Produces:
  - `grant_goal(grant: Grant) -> str`
  - `host_allowed(console_url: str, allowlist: list[str] | None = None) -> bool`
  - `verify_active(html: str, grant: Grant) -> bool`
  - `completed_event(grant, *, success: bool, reason: str | None, actions: list, watch_url: str | None, mode: str, turn_count: int) -> AuditEvent`

- [ ] **Step 1: Write the failing tests**

```python
from computer_use import completed_event, grant_goal, host_allowed, verify_active


def test_goal_names_resource_principal_and_expiry(grant):
    text = grant_goal(grant)
    assert "bucket-analytics-raw" in text
    assert "u-newhire-1" in text
    assert "Do not grant any other resource" in text


def test_host_allowed_rejects_unknown():
    assert host_allowed("http://127.0.0.1:8765/", allowlist=["127.0.0.1", "localhost"]) is True
    assert host_allowed("https://evil.example/", allowlist=["127.0.0.1"]) is False


def test_verify_active_reads_data_attributes(grant):
    html = '<ul id="active-grants"><li data-resource="bucket-analytics-raw" data-principal="u-newhire-1">ok</li></ul>'
    assert verify_active(html, grant) is True
    assert verify_active("<ul id='active-grants'></ul>", grant) is False


def test_completed_event_shape(grant):
    event = completed_event(
        grant,
        success=False,
        reason="turn_budget",
        actions=[{"intent": "click Grant access", "name": "click", "args": {}}],
        watch_url=None,
        mode="playwright",
        turn_count=20,
    )
    assert event.type.value == "action_executed"
    assert event.actor == "agent"
    assert event.payload["phase"] == "completed"
    assert event.payload["success"] is False
    assert event.payload["reason"] == "turn_budget"
    assert event.grant_id == grant.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_computer_use.py -v`

Expected: FAIL — functions missing

- [ ] **Step 3: Write those four functions in `computer_use.py`.** Keep `execute_grant` raising `NotImplementedError` until Task 8. `completed_event` should call `audit_logger.log` so tests that only call `completed_event` still get a typed event (return the event). `reason` must be one of the closed set or `None` when `success=True`.

- [ ] **Step 4: Run tests and make sure they pass**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_computer_use.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-runtime/computer_use.py agent-runtime/tests/test_computer_use.py
git commit -m "$(cat <<'EOF'
Add computer-use goal, host allowlist, and verify helpers.

EOF
)"
```

---

### Task 8: Playwright `execute_grant` against the mock console

**Files:**
- Modify: `agent-runtime/computer_use.py`
- Modify: `agent-runtime/tests/test_computer_use.py`

**Interfaces:**
- Consumes: Task 6 console, Task 7 helpers
- Produces: `execute_grant(grant, console_url, *, mode: str | None = None, watch_url: str | None = None) -> AuditEvent`

Behavior when `mode` or `EXECUTE_GRANT_MODE` is `playwright`:

1. Log `phase=started` via `audit_logger.log`.
2. If `host_allowed` is false, return completed `unknown_host`.
3. Launch Playwright Chromium (headless in tests), open `console_url`.
4. Click **Grant access** on the card whose visible name matches the grant (`bucket-analytics-raw` → `analytics-raw`).
5. Fill **Principal** with `grant.requester_id`, **Expires** with `grant.expires_at.date().isoformat()`, click **Confirm**.
6. Read `#active-grants` HTML; `verify_active`.
7. Return completed event `success=True` or `verify_failed`.

Turn budget for playwright path is one scripted attempt, not 20 vision turns.

- [ ] **Step 1: Write the failing test**

```python
import threading
from computer_use import execute_grant
from mock_console.server import serve_in_thread


def test_playwright_execute_grant_marks_active(grant):
    server = serve_in_thread(port=8765)
    try:
        event = execute_grant(grant, "http://127.0.0.1:8765/", mode="playwright")
        assert event.payload["phase"] == "completed"
        assert event.payload["success"] is True
        assert event.payload["mode"] == "playwright"
    finally:
        server.shutdown()
```

Add `serve_in_thread` to `mock_console/server.py` that starts `ThreadingHTTPServer` on a background thread and returns the server (with `.shutdown()`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_computer_use.py::test_playwright_execute_grant_marks_active -v`

Expected: FAIL — `execute_grant` still `NotImplementedError`

- [ ] **Step 3: Implement Playwright `execute_grant`.** If Playwright browsers are missing, the test may fail with an install hint — run `playwright install chromium` once in the environment, then re-run. Do not skip the test.

- [ ] **Step 4: Run tests and make sure they pass**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_computer_use.py -v`

Expected: PASS including the live local Chromium test

- [ ] **Step 5: Commit**

```bash
git add agent-runtime/computer_use.py agent-runtime/mock_console/server.py agent-runtime/tests/test_computer_use.py
git commit -m "$(cat <<'EOF'
Execute grants on the mock console with Playwright.

EOF
)"
```

---

### Task 9: Gemini Computer Use loop (mocked client) + Modal endpoints

**Files:**
- Modify: `agent-runtime/computer_use.py`
- Modify: `agent-runtime/modal_app.py`
- Create: `agent-runtime/tests/test_modal_payloads.py`

**Interfaces:**
- Consumes: `parse_request`, `execute_grant`, `Grant`, `Requester`
- Produces:
  - `run_computer_use_loop(grant, page, client, *, max_turns=20) -> dict` with keys `success`, `reason`, `actions`, `turn_count`
  - `parse_request_endpoint` / `execute_grant_endpoint` that return JSON (or raise HTTP-like errors)

`run_computer_use_loop` calls an injectable `client.next_action(screenshot_png: bytes, goal: str) -> dict | None`. `None` means the model thinks it is done (then verify). A dict is `{name, args, intent, safety}` where `safety` is `allowed` / `require_confirmation` / `blocked`. On `blocked`, stop with reason `blocked`. On our allowlisted host, `require_confirmation` is treated as `allowed`. After each action, execute via Playwright (`click` at x,y or `type` or `navigate`). Stop at `max_turns` with `turn_budget`. Missing Gemini key in live default client → `gemini_unavailable` without raising into backend grant logic.

Modal `parse_request_endpoint` body: `{raw_text, requester, known_resource_ids}` → `AccessRequest.model_dump(mode="json")`.

Modal `execute_grant_endpoint` body: `{grant, console_url, callback_base_url?}`. If `callback_base_url` is set, `set_emitter(make_emitter(...))` before execute. Return `{sandbox_id: "local", watch_url: payload.get("watch_url"), grant_id, event: <completed dump>}`. Image must pip-install `pydantic-ai`, `logfire`, `google-genai`, `playwright`, `httpx`, `fastapi` and install Chromium in the image via `playwright install chromium` run command. Remove unused `anthropic` unless already imported.

- [ ] **Step 1: Write the failing tests**

In `test_computer_use.py`:

```python
def test_loop_stops_on_blocked(grant):
    class Client:
        def next_action(self, screenshot_png, goal):
            return {"name": "click", "args": {"x": 1, "y": 1}, "intent": "nope", "safety": "blocked"}

    class Page:
        def screenshot(self, type="png"):
            return b"png"

        def mouse(self):
            raise AssertionError("should not click when blocked")

    result = run_computer_use_loop(grant, Page(), Client(), max_turns=5)
    assert result["success"] is False
    assert result["reason"] == "blocked"


def test_loop_turn_budget(grant):
    class Client:
        def next_action(self, screenshot_png, goal):
            return {"name": "wait", "args": {}, "intent": "look", "safety": "allowed"}

    class Page:
        def screenshot(self, type="png"):
            return b"png"

    result = run_computer_use_loop(grant, Page(), Client(), max_turns=3)
    assert result["reason"] == "turn_budget"
    assert result["turn_count"] == 3
```

In `test_modal_payloads.py`, import the endpoint functions and call them with a runner-injected parse if needed. If endpoints construct real Gemini, extract a `handle_parse(payload, *, parse=parse_request)` helper and test that. Same for execute: `handle_execute(payload, *, execute=execute_grant)`.

```python
def test_handle_parse_returns_access_request_dict(requester):
    from modal_app import handle_parse
    from gemini_parser import ParseFields

    def parse(raw_text, requester, known, runner=None):
        from gemini_parser import _build_request
        return _build_request(raw_text, requester, "atlas-migration", ["bucket-analytics-raw"], 14)

    out = handle_parse(
        {
            "raw_text": "I need analytics-raw",
            "requester": requester.model_dump(),
            "known_resource_ids": ["bucket-analytics-raw"],
        },
        parse=parse,
    )
    assert out["resource_ids"] == ["bucket-analytics-raw"]


def test_handle_execute_calls_execute(grant):
    from modal_app import handle_execute
    from shared.schemas import AuditEvent, AuditEventType

    def execute(g, url, **kw):
        return AuditEvent(
            id="evt",
            type=AuditEventType.ACTION_EXECUTED,
            actor="agent",
            detail="ok",
            grant_id=g.id,
            request_id=g.request_id,
            payload={"phase": "completed", "success": True, "watch_url": None},
        )

    out = handle_execute(
        {"grant": grant.model_dump(mode="json"), "console_url": "http://127.0.0.1:8765/"},
        execute=execute,
    )
    assert out["grant_id"] == grant.id
    assert out["event"]["payload"]["success"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_computer_use.py tests/test_modal_payloads.py -v`

Expected: FAIL — `run_computer_use_loop` / `handle_parse` missing

- [ ] **Step 3: Implement loop + `handle_parse` / `handle_execute`. Point the Modal endpoint functions at those handles. Do not leave `NotImplementedError`.**

- [ ] **Step 4: Run the full agent-runtime suite**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/ -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-runtime/computer_use.py agent-runtime/modal_app.py agent-runtime/tests
git commit -m "$(cat <<'EOF'
Add Gemini computer-use loop hooks and Modal parse/execute handles.

EOF
)"
```

---

### Task 10: Backend `POST /audit` so Modal can write the trail

**Files:**
- Modify: `backend-api/main.py`
- Create: `backend-api/tests/test_audit_post.py`

**Interfaces:**
- Consumes: `AuditEvent`
- Produces: `POST /audit` appends the event (server still assigns `id` / `prev_hash` / `timestamp` if missing or always overwrites id/hash/timestamp to stay consistent with existing trust rules)

Trust rule in `main.py`: audit ids/hashes/timestamps are server-assigned. So `POST /audit` accepts the body but **reassigns** `id`, `prev_hash`, `timestamp` via `_audit(event.type, event.actor, event.detail, request_id=..., grant_id=..., escalation_id=..., payload=event.payload, trace_id=event.trace_id)`.

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient
from main import app
from shared.schemas import AuditEventType


def test_post_audit_appends_action_executed():
    client = TestClient(app)
    resp = client.post(
        "/audit",
        json={
            "id": "client-supplied-ignored",
            "type": "action_executed",
            "actor": "agent",
            "detail": "computer-use session started",
            "request_id": "r-1",
            "grant_id": "g-1",
            "payload": {"phase": "started", "watch_url": "https://example/vnc"},
            "trace_id": "lf-1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "action_executed"
    assert body["id"] != "client-supplied-ignored"
    assert body["payload"]["phase"] == "started"
    listed = client.get("/audit").json()
    assert any(e["id"] == body["id"] for e in listed)
```

`backend-api` may need `httpx` already in requirements for TestClient. Add `httpx` to `backend-api/requirements.txt` if the test cannot import TestClient.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend-api && PYTHONPATH=.:.. pytest tests/test_audit_post.py -v`

Expected: FAIL — 405 or 404 on POST /audit

- [ ] **Step 3: Add the endpoint using `_audit` so the hash chain stays intact.**

- [ ] **Step 4: Run tests and make sure they pass**

Run: `cd backend-api && PYTHONPATH=.:.. pytest tests/test_audit_post.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend-api/main.py backend-api/tests/test_audit_post.py backend-api/requirements.txt
git commit -m "$(cat <<'EOF'
Accept agent-runtime ACTION_EXECUTED events on POST /audit.

EOF
)"
```

---

### Task 11: A2UI `compose_ui` for track 1

**Files:**
- Create: `agent-runtime/a2ui.py`
- Create: `agent-runtime/tests/test_a2ui.py`
- Modify: `agent-runtime/modal_app.py` — add `handle_compose`

**Interfaces:**
- Consumes: `Grant`, `EscalationCase`, `UISpec`, `UIComponentSpec`
- Produces:
  - `CATALOG = ("GrantCard", "PendingApprovalCard", "AuditTimeline", "ConsoleWatchCard")`
  - `compose_ui(grants, cases, role, *, viewer_id: str, runner=None) -> UISpec`
  - `handle_compose(payload, *, compose=compose_ui) -> dict`

Catalog is the only legal `component` names. Off-catalog names are dropped. After generation, drop any panel whose `props.grant_id` / `props.escalation_id` is not in the viewer's `grants` / `cases`. Stable ids: `grant-{grant.id}`, `case-{case.id}`, `audit-{viewer_id}`, `watch-{grant.id}`.

Roles:
- `requester`: GrantCards for active grants, PendingApprovalCard for that requester's pending cases
- `approver`: PendingApprovalCard first (cases where viewer is in `required_approver_ids`), then GrantCards
- `auditor`: AuditTimeline plus GrantCards

Fallback when `runner` is None or raises: deterministic composition (no Gemini) using those rules. Live default runner uses Pydantic AI `output_type=UISpec` with the catalog listed in the system prompt.

- [ ] **Step 1: Write the failing tests**

```python
from datetime import datetime, timedelta, timezone

from a2ui import CATALOG, compose_ui
from shared.schemas import EscalationCase, Grant, UIComponentSpec, UISpec


def _grant():
    now = datetime.now(timezone.utc)
    return Grant(
        id="g-1",
        request_id="r-1",
        resource_id="bucket-analytics-raw",
        requester_id="u-newhire-1",
        expires_at=now + timedelta(days=14),
    )


def _case():
    return EscalationCase(
        id="c-1",
        request_id="r-1",
        resource_id="bq-project-x-finance",
        required_approver_ids=["u-manager-1"],
        requester_id="u-newhire-1",
        requested_duration_days=14,
    )


def test_fallback_requester_layout():
    spec = compose_ui([_grant()], [_case()], "requester", viewer_id="u-newhire-1")
    names = [p.component for p in spec.panels]
    assert "GrantCard" in names
    assert "PendingApprovalCard" in names
    assert spec.panels[0].id == "grant-g-1"


def test_drops_off_catalog_from_runner():
    def runner(prompt: str) -> UISpec:
        return UISpec(
            requester_id="u-newhire-1",
            panels=[
                UIComponentSpec(id="x", component="EvilWidget", props={"grant_id": "g-1"}),
                UIComponentSpec(id="grant-g-1", component="GrantCard", props={"grant_id": "g-1", "resource_id": "bucket-analytics-raw"}),
            ],
        )

    spec = compose_ui([_grant()], [], "requester", viewer_id="u-newhire-1", runner=runner)
    assert all(p.component in CATALOG for p in spec.panels)
    assert all(p.component != "EvilWidget" for p in spec.panels)


def test_drops_panels_not_in_viewer_set():
    def runner(prompt: str) -> UISpec:
        return UISpec(
            requester_id="u-newhire-1",
            panels=[
                UIComponentSpec(id="grant-g-1", component="GrantCard", props={"grant_id": "g-1"}),
                UIComponentSpec(id="grant-other", component="GrantCard", props={"grant_id": "g-other"}),
            ],
        )

    spec = compose_ui([_grant()], [], "requester", viewer_id="u-newhire-1", runner=runner)
    assert [p.props.get("grant_id") for p in spec.panels] == ["g-1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_a2ui.py -v`

Expected: FAIL — module missing

- [ ] **Step 3: Implement `a2ui.py` and `handle_compose` on `modal_app.py`.** `handle_compose` body: `{grants, cases, role, viewer_id}`.

- [ ] **Step 4: Run tests and make sure they pass**

Run: `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_a2ui.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-runtime/a2ui.py agent-runtime/tests/test_a2ui.py agent-runtime/modal_app.py
git commit -m "$(cat <<'EOF'
Add A2UI compose_ui against the fixed component catalog.

EOF
)"
```

---

## Out of scope (later plans)

- Scoped MCP server
- Live noVNC Modal sandbox image (Task 8 proves the loop; Modal image gets Playwright; headed VNC can be a follow-up once this suite is green)
- Jev
- Real GCP IAM
- Wiring `_issue_grant` to call execute URL (track 5 build order item 6 — they own the enqueue)

## Self-review

- Spec coverage: parse enum/constrain, Logfire-if-token, summaries from PolicyDecision, mock console, Playwright execute, Gemini CU loop (mocked), Modal handles, POST /audit, A2UI compose_ui, fire-and-callback emitter.
- No Jev/Anthropic/MCP in tasks.
- Types: `ParseFields`, `parse_request(..., runner=)`, `execute_grant(..., mode=)`, `handle_parse` / `handle_execute` / `handle_compose`, `compose_ui`, `make_emitter`, `completed_event`.
- Live Gemini is never required for pytest.
