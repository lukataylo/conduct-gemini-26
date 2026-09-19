# Generative Console Agent (text chat + mic stub) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Aperture's one-click hardcoded DemoBar "Request as {name}" with a free-text console agent that may only call `request_access` / `list_scope` / `explain_decision`; policy still decides, and the Live mic stays visible and disabled.

**Architecture:** Aperture posts `{viewer_id, message, conversation_id?, confirm?}` to `POST /agent/turn`. The backend looks up the viewer in `KNOWN_REQUESTERS`, runs an injectable Pydantic AI console agent (`parse_model()`, `google:` prefix), and maps `request_access` onto existing `_parse_nl` + `_evaluate_request`. First `request_access` intent returns a shell confirm card (parsed preview only); `confirm=true` evaluates. LLMs never write a `Grant`.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, Pydantic AI, Logfire, pytest, React 18, Vite (proxy `/api` → `:8000`), existing Aperture CSS (black, Doto/Geist, `.nb` pills).

## Global Constraints

- LLMs never grant. Agent may only `request_access` → parse → policy (`_evaluate_request`). Agent must refuse `grant`, `vote`, `close_project`, `patch_policy`.
- Model: `parse_model()` from `agent-runtime/gemini_models.py` — default `google:gemini-3.8-flash` (Pydantic AI v2 prefix is `google:`, not `google-gla:`). `export_gemini_keys()` + `logfire.configure(send_to_logfire="if-token-present")` + `logfire.instrument_pydantic_ai()`.
- Unit tests default offline: inject a fake runner / tool impls. Live Gemini only in optional smoke, never required.
- `request_access` must use the NL path (no client `resource_ids`). Viewer is looked up server-side like `/requests`; ignore client team/role.
- Confirmation card is shell, not an A2UI catalog component. Do not implement Gemini Live WebRTC/native-audio. Mic visible + disabled; `title` and `aria-label` = `voice offline — use chat`.
- Boot app stays `generative-ui/src/main.tsx` → `aperture/App.tsx`. Do not resurrect registry `App.tsx`.
- Do not rewrite Computer Use, mock console, MCP protocol (`mcp_serve.py` / `tools_for_grants`), Modal sandbox, or Onboard's MCP connect/`GET /tools` beat.
- Onboard may keep posting `{raw_text, requester_id}` to `/requests` (already NL). The product chat path is the console dock → `/agent/turn`.
- DemoBar stays presenter chrome: keep **Seed peers**, **Approve all**, **Call tool as**, **Close project**. Remove **Request as {name}** (the hardcoded typed `AccessRequest`).
- Person switcher stays. Composer uses `selected` as `viewer_id`. When `selected === "all"`, composer is disabled.
- `GET /grants` default stays active + unexpired. Do not POST synthetic `ACTION_EXECUTED` from the console agent. `REAL_GCP` stays unused by the agent.
- Do not commit `env.local`, `.env`, keys, recordings, or the dirty `agent-runtime/computer_use.py` WIP.
- Work on `main`. `git pull --rebase origin main` before the first task and before every push. Never force-push. One concern per commit; message is why, not what.
- North star: `docs/superpowers/specs/2026-09-19-generative-console-design.md` § Chat + § Gemini Live (mic stub only). Conventions: `docs/console-and-mcp.md`.
- Known resources: `bucket-analytics-raw`, `bq-project-x-finance`, `sql-prod-primary`. Alex = `u-newhire-1`. Policy today: bucket auto-grants, finance escalates, `sql-prod-primary` (CRITICAL) **escalates** (`always_escalate_tiers`) — do not invent a deny.
- Example user texts must work as inputs, not as the only hardcoded send path.

## File map

- Create: `agent-runtime/console_agent.py` — Pydantic AI agent, injectable deps/runner, system prompt
- Create: `agent-runtime/tests/test_console_agent.py`
- Create: `backend-api/tests/conftest.py` — autouse reset of in-memory stores
- Create: `backend-api/tests/test_agent_turn.py`
- Create: `generative-ui/src/aperture/Composer.tsx` — dock, transcript, confirm card, textarea, send
- Modify: `backend-api/main.py` — `POST /agent/turn`, `AGENT_TURN_IMPL`, `CONVERSATIONS`
- Modify: `generative-ui/src/aperture/DemoBar.tsx` — drop Request as {name}
- Modify: `generative-ui/src/aperture/App.tsx` — dock + disabled mic in chrome
- Modify: `generative-ui/src/aperture/api.ts` — `postAgentTurn`
- Modify: `generative-ui/src/aperture/aperture.css` — dock / composer / confirm / mic
- Optional: `env.example` — comment for `GEMINI_PARSE_MODEL`

Do not modify: `agent-runtime/computer_use.py`, `mcp_serve.py`, `mcp_server.py`, `Onboard.tsx` (except if a type import is required — prefer none).

---

### Task 1: Console agent unit (injectable tools, refuse illegal verbs)

**Files:**
- Create: `agent-runtime/console_agent.py`
- Create: `agent-runtime/tests/test_console_agent.py`

**Interfaces:**
- Consumes: `parse_model()` from `gemini_models.py`; `export_gemini_keys()` from `envutil.py`; `Requester` from `shared.schemas`
- Produces:
  - `LEGAL_TOOLS = ("request_access", "list_scope", "explain_decision")`
  - `ILLEGAL_TOOLS = ("grant", "vote", "close_project", "patch_policy")`
  - `SYSTEM_PROMPT: str` — must name each illegal tool as refused; must say the model never grants and must use `request_access` for access asks
  - `class ConsoleAgentDeps` with `viewer: Requester`, `request_access: Callable[[str], dict]`, `list_scope: Callable[[], dict]`, `explain_decision: Callable[[str | None, str | None], dict]`
  - `class ConsoleTurn(BaseModel)` with `reply: str`, `tools_used: list[str] = []`, `request_result: dict | None = None`, `conversation_id: str = ""`
  - `ConsoleRunner = Callable[[str, ConsoleAgentDeps, str], ConsoleTurn]` — `(message, deps, system_prompt) -> ConsoleTurn`
  - `run_console_turn(message: str, deps: ConsoleAgentDeps, *, runner: ConsoleRunner | None = None, conversation_id: str | None = None) -> ConsoleTurn`
  - `default_console_runner(message, deps, system_prompt) -> ConsoleTurn` — builds a Pydantic AI `Agent` with `parse_model()`, `deps_type=ConsoleAgentDeps`, the three tools, logfire + `export_gemini_keys()`. Unit tests must not call this.

- [ ] **Step 1: Write the failing tests**

Create `agent-runtime/tests/test_console_agent.py`:

```python
from console_agent import (
    ILLEGAL_TOOLS,
    LEGAL_TOOLS,
    SYSTEM_PROMPT,
    ConsoleAgentDeps,
    ConsoleTurn,
    run_console_turn,
)
from shared.schemas import Requester

ALEX = Requester(
    id="u-newhire-1",
    name="Alex Chen",
    role="Software Engineer (new hire)",
    team="data-platform",
    manager_id="u-manager-1",
)


def _deps(**overrides) -> ConsoleAgentDeps:
    def request_access(raw_text: str) -> dict:
        return {
            "status": "evaluated",
            "request_id": "r-1",
            "results": [{"resource_id": "bucket-analytics-raw", "status": "granted"}],
        }

    return ConsoleAgentDeps(
        viewer=ALEX,
        request_access=overrides.get("request_access", request_access),
        list_scope=overrides.get("list_scope", lambda: {"grants": [], "cases": []}),
        explain_decision=overrides.get(
            "explain_decision",
            lambda request_id=None, resource_id=None: {"explanation": "typed reason"},
        ),
    )


def test_legal_tools_are_exactly_the_three():
    assert LEGAL_TOOLS == ("request_access", "list_scope", "explain_decision")
    for name in ILLEGAL_TOOLS:
        assert name not in LEGAL_TOOLS


def test_system_prompt_refuses_illegal_verbs():
    lowered = SYSTEM_PROMPT.lower()
    for name in ILLEGAL_TOOLS:
        assert name in lowered
    assert "never grant" in lowered or "must not grant" in lowered


def test_request_access_returns_evaluate_payload():
    seen: list[str] = []

    def request_access(raw_text: str) -> dict:
        seen.append(raw_text)
        return {
            "status": "evaluated",
            "request_id": "r-bucket",
            "results": [
                {"resource_id": "bucket-analytics-raw", "status": "granted", "grant_id": "g-1"}
            ],
        }

    def runner(message, deps, system_prompt):
        assert "never grant" in system_prompt.lower() or "must not grant" in system_prompt.lower()
        payload = deps.request_access(message)
        return ConsoleTurn(
            reply="I submitted that access request to policy.",
            tools_used=["request_access"],
            request_result=payload,
        )

    turn = run_console_turn(
        "Need read on the analytics-raw GCS bucket so I can inspect last week's ingest.",
        _deps(request_access=request_access),
        runner=runner,
        conversation_id="c-1",
    )
    assert turn.conversation_id == "c-1"
    assert turn.tools_used == ["request_access"]
    assert turn.request_result["request_id"] == "r-bucket"
    assert turn.request_result["results"][0]["status"] == "granted"
    assert "Grant(" not in str(turn.request_result)
    assert seen  # tool received the human text, not client resource ids


def test_refuse_close_does_not_call_tools():
    calls: list[str] = []

    def request_access(raw_text: str) -> dict:
        calls.append("request_access")
        raise AssertionError("request_access must not run for a close/vote ask")

    def runner(message, deps, system_prompt):
        for name in ILLEGAL_TOOLS:
            assert name in system_prompt.lower()
        assert "shut" in message.lower() or "revoke" in message.lower()
        return ConsoleTurn(
            reply="I cannot close Atlas, cast votes, or revoke grants. Ask me to request access or explain a decision.",
            tools_used=[],
        )

    turn = run_console_turn(
        "Revoke everything and shut Atlas down.",
        _deps(request_access=request_access),
        runner=runner,
    )
    assert turn.tools_used == []
    assert calls == []
    assert "cannot" in turn.reply.lower() or "can't" in turn.reply.lower()


def test_list_scope_and_explain_do_not_grant():
    def runner(message, deps, system_prompt):
        scope = deps.list_scope()
        explained = deps.explain_decision(request_id="r-1", resource_id="bq-project-x-finance")
        assert "I need" not in str(explained)
        return ConsoleTurn(
            reply=f"{scope} {explained}",
            tools_used=["list_scope", "explain_decision"],
            request_result=None,
        )

    turn = run_console_turn(
        "What do I currently have, and why is finance still pending?",
        _deps(),
        runner=runner,
    )
    assert "request_access" not in turn.tools_used
    assert turn.request_result is None


def test_run_console_turn_assigns_conversation_id_when_missing():
    def runner(message, deps, system_prompt):
        return ConsoleTurn(reply="ok", tools_used=[])

    turn = run_console_turn("hello", _deps(), runner=runner)
    assert turn.conversation_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run from repo root (agent-runtime on `PYTHONPATH`):

```bash
cd /Users/vikkash/dev/conduct-gemini-26
PYTHONPATH=agent-runtime:. python -m pytest agent-runtime/tests/test_console_agent.py -v
```

Expected: FAIL with `ModuleNotFoundError: console_agent` or import error.

- [ ] **Step 3: Write minimal implementation**

Create `agent-runtime/console_agent.py`:

```python
"""Console agent: talk to the human aperture. Never grants — tools request or explain."""
from __future__ import annotations

import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

sys.path.append(str(Path(__file__).resolve().parents[1]))

from envutil import export_gemini_keys  # noqa: E402
from gemini_models import parse_model  # noqa: E402
from shared.schemas import Requester  # noqa: E402

LEGAL_TOOLS = ("request_access", "list_scope", "explain_decision")
ILLEGAL_TOOLS = ("grant", "vote", "close_project", "patch_policy")

SYSTEM_PROMPT = """You are the Aperture console agent for one human viewer.

You never grant access. You never write a Grant. Policy-engine decides.
You may only use these tools: request_access, list_scope, explain_decision.

Illegal — refuse, do not call any tool, do not claim you did it:
- grant
- vote (Approve / Deny)
- close_project (including "shut Atlas down" or revoke everything)
- patch_policy

If the human asks for access, call request_access with their raw_text.
If they ask what they have or what is pending, call list_scope.
If they ask why a decision happened, call explain_decision with a request_id or resource_id.
Do not invent resource ids. Do not POST votes. Do not close projects.
"""

@dataclass
class ConsoleAgentDeps:
    viewer: Requester
    request_access: Callable[[str], dict]
    list_scope: Callable[[], dict]
    explain_decision: Callable[[str | None, str | None], dict]


class ConsoleTurn(BaseModel):
    reply: str
    tools_used: list[str] = Field(default_factory=list)
    request_result: dict | None = None
    conversation_id: str = ""


ConsoleRunner = Callable[[str, ConsoleAgentDeps, str], ConsoleTurn]

_LOGFIRE_READY = False


def _ensure_logfire() -> None:
    global _LOGFIRE_READY
    if _LOGFIRE_READY:
        return
    import logfire

    logfire.configure(send_to_logfire="if-token-present")
    logfire.instrument_pydantic_ai()
    _LOGFIRE_READY = True


def default_console_runner(message: str, deps: ConsoleAgentDeps, system_prompt: str) -> ConsoleTurn:
    """Live Gemini path. Unit tests inject `runner` and never call this."""
    from pydantic_ai import Agent, RunContext

    export_gemini_keys()
    _ensure_logfire()
    used: list[str] = []
    last_request: dict | None = None
    agent = Agent(parse_model(), deps_type=ConsoleAgentDeps, system_prompt=system_prompt)

    @agent.tool
    def request_access(ctx: RunContext[ConsoleAgentDeps], raw_text: str) -> dict:
        nonlocal last_request
        used.append("request_access")
        last_request = ctx.deps.request_access(raw_text)
        return last_request

    @agent.tool
    def list_scope(ctx: RunContext[ConsoleAgentDeps]) -> dict:
        used.append("list_scope")
        return ctx.deps.list_scope()

    @agent.tool
    def explain_decision(
        ctx: RunContext[ConsoleAgentDeps],
        request_id: str | None = None,
        resource_id: str | None = None,
    ) -> dict:
        used.append("explain_decision")
        return ctx.deps.explain_decision(request_id, resource_id)

    result = agent.run_sync(message, deps=deps)
    return ConsoleTurn(reply=str(result.output), tools_used=used, request_result=last_request)


def run_console_turn(
    message: str,
    deps: ConsoleAgentDeps,
    *,
    runner: ConsoleRunner | None = None,
    conversation_id: str | None = None,
) -> ConsoleTurn:
    run = runner or default_console_runner
    turn = run(message, deps, SYSTEM_PROMPT)
    cid = conversation_id or turn.conversation_id or str(uuid.uuid4())
    if turn.conversation_id == cid:
        return turn
    return turn.model_copy(update={"conversation_id": cid})
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/vikkash/dev/conduct-gemini-26
PYTHONPATH=agent-runtime:. python -m pytest agent-runtime/tests/test_console_agent.py -v
```

Expected: PASS, all tests, pristine output.

Then run the existing agent-runtime suite once:

```bash
PYTHONPATH=agent-runtime:. python -m pytest agent-runtime/tests -v --ignore=agent-runtime/tests/test_computer_use.py
```

Expected: PASS (skip CU if this machine is mid-WIP; do not edit `computer_use.py`).

- [ ] **Step 5: Commit**

```bash
git pull --rebase origin main
git add agent-runtime/console_agent.py agent-runtime/tests/test_console_agent.py
git commit -m "$(cat <<'EOF'
Let the console agent choose tools without ever granting.

EOF
)"
git pull --rebase origin main
git push origin main
```

Do not stage `agent-runtime/computer_use.py`, `env.local`, recordings, or `.env`.

---

### Task 2: `POST /agent/turn` wires injected agent through policy

**Files:**
- Create: `backend-api/tests/conftest.py`
- Create: `backend-api/tests/test_agent_turn.py`
- Modify: `backend-api/main.py` — add `AGENT_TURN_IMPL`, `CONVERSATIONS`, `AgentTurnIn` / `AgentTurnOut`, `POST /agent/turn`, `_console_request_access` / `_console_list_scope` / `_console_explain_decision`

**Interfaces:**
- Consumes: `run_console_turn`, `ConsoleAgentDeps`, `ConsoleTurn` from `console_agent`; existing `_parse_nl`, `_evaluate_request`, `KNOWN_REQUESTERS`, `active_grants`, `ESCALATIONS`, `AUDIT_LOG`, `PARSE_IMPL`
- Produces:
  - `AGENT_TURN_IMPL: Callable[..., ConsoleTurn] | None = None` — if set, `run_console_turn(..., runner=AGENT_TURN_IMPL)`
  - `CONVERSATIONS: dict[str, dict]` — `{conversation_id: {"pending_request": AccessRequest | None, "pending_raw": str | None}}`
  - `class AgentTurnIn(BaseModel)`: `viewer_id: str`, `message: str`, `conversation_id: str | None = None`, `confirm: bool = False`
  - `class AgentTurnOut(BaseModel)`: `reply: str`, `tools_used: list[str]`, `request_result: dict | None = None`, `conversation_id: str`
  - `POST /agent/turn` → `AgentTurnOut`. Unknown `viewer_id` → HTTP 400 with `unknown requester`.
  - `_console_request_access(raw_text: str, viewer: Requester) -> dict` — `_parse_nl` then `_evaluate_request`; return `{status: "evaluated", request_id, results}`. Never accept client `resource_ids`.
  - `_console_list_scope(viewer) -> dict` — viewer's **active** grants + **pending** cases only.
  - `_console_explain_decision(viewer, request_id=None, resource_id=None) -> dict` — typed audit / policy reason from `POLICY_EVALUATED` (or escalation reason). Prefer `summarize_decision` only when a `PolicyDecision` is in hand; **never** pass requester `raw_text` into the summarizer. Fallback = audit `detail`.
  - Task 2 evaluates on the first `request_access` (confirm gate is Task 3). Tests inject `PARSE_IMPL` and `AGENT_TURN_IMPL` so Gemini is never called.

- [ ] **Step 1: Write the failing tests**

Create `backend-api/tests/conftest.py`:

```python
import pytest

import main


@pytest.fixture(autouse=True)
def reset_store():
    main.REQUESTS.clear()
    main.GRANTS.clear()
    main.ESCALATIONS.clear()
    main.AUDIT_LOG.clear()
    main.WATCH_URLS.clear()
    main.CONVERSATIONS.clear()
    main.PARSE_IMPL = None
    main.AGENT_TURN_IMPL = None
    main.EXECUTE_ENQUEUE_IMPL = None
    main.COMPOSE_IMPL = None
    yield
    main.REQUESTS.clear()
    main.GRANTS.clear()
    main.ESCALATIONS.clear()
    main.AUDIT_LOG.clear()
    main.WATCH_URLS.clear()
    main.CONVERSATIONS.clear()
    main.PARSE_IMPL = None
    main.AGENT_TURN_IMPL = None
    main.EXECUTE_ENQUEUE_IMPL = None
    main.COMPOSE_IMPL = None
```

Create `backend-api/tests/test_agent_turn.py`:

```python
from fastapi.testclient import TestClient

import main
from console_agent import ConsoleTurn
from shared.schemas import AccessRequest, Requester

ALEX_ID = "u-newhire-1"

BUCKET_TEXT = (
    "Need read on the analytics-raw GCS bucket so I can inspect last week's "
    "ingest for the data-platform onboarding task. Two weeks is enough."
)
FINANCE_TEXT = (
    "I need the project-x-finance BigQuery dataset to reconcile Atlas invoice "
    "lines. I'm on data-platform, done by Nov 15."
)
BOTH_TEXT = (
    "Need read on the analytics-raw GCS bucket so I can inspect last week's "
    "ingest, and the project-x-finance BigQuery dataset to reconcile Atlas "
    "invoice lines. Two weeks is enough."
)
SQL_TEXT = (
    "Grant me access to the prod-primary Cloud SQL instance so I can patch a "
    "customer row. Need it today."
)
CLOSE_TEXT = "Revoke everything and shut Atlas down."


def _parse(raw_text: str, requester: Requester) -> AccessRequest:
    ids: list[str] = []
    low = raw_text.lower()
    if "analytics-raw" in low or "gcs bucket" in low:
        ids.append("bucket-analytics-raw")
    if "finance" in low or "project-x" in low:
        ids.append("bq-project-x-finance")
    if "prod-primary" in low or "cloud sql" in low:
        ids.append("sql-prod-primary")
    days = 14
    if "today" in low:
        days = 1
    return AccessRequest(
        id="client-ignored",
        requester=requester,
        task_description=raw_text,
        project="atlas-migration",
        resource_ids=ids,
        requested_duration_days=days,
        raw_text=raw_text,
    )


def _client() -> TestClient:
    main.PARSE_IMPL = _parse
    return TestClient(main.app)


def test_unknown_viewer_is_400():
    resp = _client().post(
        "/agent/turn",
        json={"viewer_id": "no-such-user", "message": "hello"},
    )
    assert resp.status_code == 400
    assert "unknown requester" in resp.json()["detail"]


def test_injected_agent_request_access_grants_bucket_and_escalates_finance():
    def runner(message, deps, system_prompt):
        payload = deps.request_access(message)
        return ConsoleTurn(
            reply="Submitted to policy.",
            tools_used=["request_access"],
            request_result=payload,
        )

    main.AGENT_TURN_IMPL = runner
    resp = _client().post(
        "/agent/turn",
        json={"viewer_id": ALEX_ID, "message": BOTH_TEXT, "conversation_id": "c-golden"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"] == "c-golden"
    assert body["tools_used"] == ["request_access"]
    result = body["request_result"]
    assert result["status"] == "evaluated"
    by_id = {row["resource_id"]: row for row in result["results"]}
    assert by_id["bucket-analytics-raw"]["status"] == "granted"
    assert by_id["bq-project-x-finance"]["status"] == "escalated"
    assert result["request_id"] in main.REQUESTS
    assert any(g.resource_id == "bucket-analytics-raw" for g in main.GRANTS.values())
    assert any(c.resource_id == "bq-project-x-finance" for c in main.ESCALATIONS.values())


def test_sql_critical_goes_through_policy_not_client_ids():
    def runner(message, deps, system_prompt):
        return ConsoleTurn(
            reply="Submitted.",
            tools_used=["request_access"],
            request_result=deps.request_access(message),
        )

    main.AGENT_TURN_IMPL = runner
    resp = _client().post("/agent/turn", json={"viewer_id": ALEX_ID, "message": SQL_TEXT})
    assert resp.status_code == 200
    rows = resp.json()["request_result"]["results"]
    assert rows[0]["resource_id"] == "sql-prod-primary"
    assert rows[0]["status"] == "escalated"  # CRITICAL always_escalate_tiers


def test_refuse_close_does_not_close_project():
    def runner(message, deps, system_prompt):
        return ConsoleTurn(reply="I cannot close Atlas or revoke grants.", tools_used=[])

    main.AGENT_TURN_IMPL = runner
    # seed a grant via the real evaluate path so close would have something to revoke
    main.PARSE_IMPL = _parse
    seeded = main._evaluate_request(_parse(BUCKET_TEXT, main.KNOWN_REQUESTERS[ALEX_ID]))
    assert seeded["results"][0]["status"] == "granted"
    before = dict(main.GRANTS)

    resp = _client().post("/agent/turn", json={"viewer_id": ALEX_ID, "message": CLOSE_TEXT})
    assert resp.status_code == 200
    assert resp.json()["tools_used"] == []
    assert main.GRANTS.keys() == before.keys()
    assert all(not g.revoked for g in main.GRANTS.values())


def test_list_scope_is_viewer_active_and_pending_only():
    def runner(message, deps, system_prompt):
        return ConsoleTurn(
            reply="Here is your scope.",
            tools_used=["list_scope"],
            request_result=deps.list_scope(),
        )

    main.AGENT_TURN_IMPL = runner
    main.PARSE_IMPL = _parse
    main._evaluate_request(_parse(BOTH_TEXT, main.KNOWN_REQUESTERS[ALEX_ID]))

    resp = _client().post(
        "/agent/turn",
        json={"viewer_id": ALEX_ID, "message": "What do I currently have, and why is finance still pending?"},
    )
    body = resp.json()
    assert body["tools_used"] == ["list_scope"]
    scope = body["request_result"]
    assert len(scope["grants"]) == 1
    assert scope["grants"][0]["resource_id"] == "bucket-analytics-raw"
    assert len(scope["cases"]) == 1
    assert scope["cases"][0]["resource_id"] == "bq-project-x-finance"
    assert scope["cases"][0]["status"] == "pending"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/vikkash/dev/conduct-gemini-26/backend-api
PYTHONPATH=..:../agent-runtime:. python -m pytest tests/test_agent_turn.py -v
```

Expected: FAIL — `CONVERSATIONS` / `AGENT_TURN_IMPL` / `/agent/turn` missing.

- [ ] **Step 3: Write minimal implementation**

In `backend-api/main.py`:

1. Add after the existing impl hooks:

```python
AGENT_TURN_IMPL: Callable[..., object] | None = None
CONVERSATIONS: dict[str, dict] = {}
```

2. Add models + helpers + route (near other POST endpoints, after `submit_request` is fine):

```python
class AgentTurnIn(BaseModel):
    viewer_id: str
    message: str
    conversation_id: str | None = None
    confirm: bool = False


class AgentTurnOut(BaseModel):
    reply: str
    tools_used: list[str] = []
    request_result: dict | None = None
    conversation_id: str


def _console_request_access(raw_text: str, viewer: Requester) -> dict:
    parsed = _parse_nl(raw_text, viewer)
    parsed = parsed.model_copy(update={"requester": viewer, "raw_text": raw_text})
    evaluated = _evaluate_request(parsed)
    return {
        "status": "evaluated",
        "request_id": evaluated["request_id"],
        "results": evaluated["results"],
    }


def _console_list_scope(viewer: Requester) -> dict:
    grants = [g.model_dump(mode="json") for g in active_grants(viewer.id)]
    cases = [
        c.model_dump(mode="json")
        for c in ESCALATIONS.values()
        if c.status == "pending" and c.requester_id == viewer.id
    ]
    return {"grants": grants, "cases": cases}


def _console_explain_decision(
    viewer: Requester,
    request_id: str | None = None,
    resource_id: str | None = None,
) -> dict:
    for event in reversed(AUDIT_LOG):
        if event.type != AuditEventType.POLICY_EVALUATED:
            continue
        if request_id and event.request_id != request_id:
            continue
        payload_rid = (event.payload or {}).get("resource_id")
        if resource_id and payload_rid != resource_id:
            continue
        return {
            "explanation": event.detail,
            "request_id": event.request_id,
            "resource_id": payload_rid,
        }
    return {"explanation": "No typed policy decision found for that id."}


def _run_injected_or_live(message: str, viewer: Requester, conversation_id: str | None):
    _agent_runtime_on_path()
    from console_agent import ConsoleAgentDeps, run_console_turn

    deps = ConsoleAgentDeps(
        viewer=viewer,
        request_access=lambda raw: _console_request_access(raw, viewer),
        list_scope=lambda: _console_list_scope(viewer),
        explain_decision=lambda request_id=None, resource_id=None: _console_explain_decision(
            viewer, request_id, resource_id
        ),
    )
    return run_console_turn(
        message,
        deps,
        runner=AGENT_TURN_IMPL,
        conversation_id=conversation_id,
    )


@app.post("/agent/turn")
def agent_turn(body: AgentTurnIn) -> AgentTurnOut:
    viewer = KNOWN_REQUESTERS.get(body.viewer_id)
    if viewer is None:
        raise HTTPException(400, f"unknown requester '{body.viewer_id}'")
    turn = _run_injected_or_live(body.message, viewer, body.conversation_id)
    return AgentTurnOut(
        reply=turn.reply,
        tools_used=list(turn.tools_used),
        request_result=turn.request_result,
        conversation_id=turn.conversation_id,
    )
```

`confirm` is accepted on the model but unused until Task 3.

If `test_audit_post.py` breaks because `CONVERSATIONS` is missing during collection of `conftest.py`, add `CONVERSATIONS` before committing.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/vikkash/dev/conduct-gemini-26/backend-api
PYTHONPATH=..:../agent-runtime:. python -m pytest tests -v
```

Expected: PASS including `test_audit_post.py` and `test_agent_turn.py`.

- [ ] **Step 5: Commit**

```bash
git pull --rebase origin main
git add backend-api/main.py backend-api/tests/conftest.py backend-api/tests/test_agent_turn.py
git commit -m "$(cat <<'EOF'
Route console chat through policy instead of client-supplied ids.

EOF
)"
git pull --rebase origin main
git push origin main
```

---

### Task 3: Confirm gate before evaluate

**Files:**
- Modify: `backend-api/main.py` — `_console_request_access` preview vs evaluate; `agent_turn` short-circuits `confirm=true`
- Modify: `backend-api/tests/test_agent_turn.py` — two-step golden path; confirm required before grants exist

**Interfaces:**
- Consumes: Task 2 `POST /agent/turn`, `CONVERSATIONS`, `_parse_nl`, `_evaluate_request`
- Produces:
  - First turn where the agent uses `request_access`: parse only. Store `pending_request` on `CONVERSATIONS[conversation_id]`. Return `request_result = {status: "needs_confirmation", preview: {resource_ids, requested_duration_days, project, raw_text}}`. **No** new `Grant` / `EscalationCase`.
  - Second call with same `conversation_id` and `confirm=true`: do **not** require a live model. Evaluate the stored `AccessRequest` via `_evaluate_request`. Return `{status: "evaluated", request_id, results, preview}`. Clear pending.
  - `confirm=true` with no pending → HTTP 400 `"nothing to confirm"`.
  - Preview `resource_ids` come from `_parse_nl`, never from the client body.

- [ ] **Step 1: Write the failing tests (update golden to two-step)**

Replace `test_injected_agent_request_access_grants_bucket_and_escalates_finance` and add:

```python
def test_request_access_needs_confirmation_before_evaluate():
    def runner(message, deps, system_prompt):
        return ConsoleTurn(
            reply="Confirm this request.",
            tools_used=["request_access"],
            request_result=deps.request_access(message),
        )

    main.AGENT_TURN_IMPL = runner
    client = _client()
    first = client.post(
        "/agent/turn",
        json={"viewer_id": ALEX_ID, "message": BOTH_TEXT, "conversation_id": "c-confirm"},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["request_result"]["status"] == "needs_confirmation"
    preview = body["request_result"]["preview"]
    assert preview["resource_ids"] == ["bucket-analytics-raw", "bq-project-x-finance"]
    assert preview["project"] == "atlas-migration"
    assert preview["requested_duration_days"] == 14
    assert main.GRANTS == {}
    assert main.ESCALATIONS == {}

    second = client.post(
        "/agent/turn",
        json={
            "viewer_id": ALEX_ID,
            "message": BOTH_TEXT,
            "conversation_id": "c-confirm",
            "confirm": True,
        },
    )
    assert second.status_code == 200
    result = second.json()["request_result"]
    assert result["status"] == "evaluated"
    by_id = {row["resource_id"]: row for row in result["results"]}
    assert by_id["bucket-analytics-raw"]["status"] == "granted"
    assert by_id["bq-project-x-finance"]["status"] == "escalated"
    assert any(g.resource_id == "bucket-analytics-raw" for g in main.GRANTS.values())


def test_confirm_without_pending_is_400():
    resp = _client().post(
        "/agent/turn",
        json={"viewer_id": ALEX_ID, "message": "ok", "confirm": True, "conversation_id": "c-none"},
    )
    assert resp.status_code == 400
    assert "nothing to confirm" in resp.json()["detail"]
```

Update `test_sql_critical_goes_through_policy_not_client_ids` to confirm after the first turn (or call `request_access` then POST `confirm=true`). Grants/escalations must be empty until confirm.

Keep `test_refuse_close_does_not_close_project` and `test_list_scope_*` unchanged in behavior (list_scope still evaluates nothing). For list_scope setup, seed with `main._evaluate_request` directly — that is not the chat confirm path.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/vikkash/dev/conduct-gemini-26/backend-api
PYTHONPATH=..:../agent-runtime:. python -m pytest tests/test_agent_turn.py -v
```

Expected: FAIL — first turn still `status == "evaluated"` and grants already exist.

- [ ] **Step 3: Write minimal implementation**

Change `_console_request_access` to accept `evaluate: bool` and change `agent_turn`:

```python
def _console_request_access(
    raw_text: str,
    viewer: Requester,
    *,
    evaluate: bool,
    conversation_id: str,
) -> dict:
    parsed = _parse_nl(raw_text, viewer)
    parsed = parsed.model_copy(update={"requester": viewer, "raw_text": raw_text})
    preview = {
        "resource_ids": list(parsed.resource_ids),
        "requested_duration_days": parsed.requested_duration_days,
        "project": parsed.project,
        "raw_text": raw_text,
    }
    slot = CONVERSATIONS.setdefault(conversation_id, {"pending_request": None, "pending_raw": None})
    slot["pending_request"] = parsed
    slot["pending_raw"] = raw_text
    if not evaluate:
        return {"status": "needs_confirmation", "preview": preview}
    evaluated = _evaluate_request(parsed)
    slot["pending_request"] = None
    slot["pending_raw"] = None
    return {
        "status": "evaluated",
        "request_id": evaluated["request_id"],
        "results": evaluated["results"],
        "preview": preview,
    }


@app.post("/agent/turn")
def agent_turn(body: AgentTurnIn) -> AgentTurnOut:
    viewer = KNOWN_REQUESTERS.get(body.viewer_id)
    if viewer is None:
        raise HTTPException(400, f"unknown requester '{body.viewer_id}'")
    conversation_id = body.conversation_id or str(__import__("uuid").uuid4())
    if body.confirm:
        slot = CONVERSATIONS.get(conversation_id) or {}
        pending = slot.get("pending_request")
        if pending is None:
            raise HTTPException(400, "nothing to confirm")
        evaluated = _evaluate_request(pending)
        slot["pending_request"] = None
        slot["pending_raw"] = None
        preview = {
            "resource_ids": list(pending.resource_ids),
            "requested_duration_days": pending.requested_duration_days,
            "project": pending.project,
            "raw_text": pending.raw_text,
        }
        return AgentTurnOut(
            reply="Policy decided.",
            tools_used=["request_access"],
            request_result={
                "status": "evaluated",
                "request_id": evaluated["request_id"],
                "results": evaluated["results"],
                "preview": preview,
            },
            conversation_id=conversation_id,
        )

    def request_access(raw_text: str) -> dict:
        return _console_request_access(
            raw_text, viewer, evaluate=False, conversation_id=conversation_id
        )

    _agent_runtime_on_path()
    from console_agent import ConsoleAgentDeps, run_console_turn

    deps = ConsoleAgentDeps(
        viewer=viewer,
        request_access=request_access,
        list_scope=lambda: _console_list_scope(viewer),
        explain_decision=lambda request_id=None, resource_id=None: _console_explain_decision(
            viewer, request_id, resource_id
        ),
    )
    turn = run_console_turn(
        body.message,
        deps,
        runner=AGENT_TURN_IMPL,
        conversation_id=conversation_id,
    )
    return AgentTurnOut(
        reply=turn.reply,
        tools_used=list(turn.tools_used),
        request_result=turn.request_result,
        conversation_id=turn.conversation_id,
    )
```

Use the existing `uuid` import already in `main.py` instead of `__import__("uuid")`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/vikkash/dev/conduct-gemini-26/backend-api
PYTHONPATH=..:../agent-runtime:. python -m pytest tests -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git pull --rebase origin main
git add backend-api/main.py backend-api/tests/test_agent_turn.py
git commit -m "$(cat <<'EOF'
Ask the human before a chat turn evaluates access.

EOF
)"
git pull --rebase origin main
git push origin main
```

---

### Task 4: Aperture composer, conversation dock, disabled Live mic

**Files:**
- Create: `generative-ui/src/aperture/Composer.tsx`
- Modify: `generative-ui/src/aperture/api.ts` — add `AgentTurn` types + `postAgentTurn`
- Modify: `generative-ui/src/aperture/DemoBar.tsx` — remove `Request as` / `ASKS` / `requestAs` / `REQUEST_TEXT` (keep Seed peers / Approve all / Call tool / Close project)
- Modify: `generative-ui/src/aperture/App.tsx` — header mic; console-view right dock
- Modify: `generative-ui/src/aperture/aperture.css` — dock, rows, confirm, mic
- Optional: `env.example` — one comment line for `GEMINI_PARSE_MODEL`

**Interfaces:**
- Consumes: `POST /agent/turn` as `AgentTurnOut`; `ALL` / `post` / `User` from `api.ts`; person `selected`
- Produces:
  - `postAgentTurn(body: {viewer_id: string; message: string; conversation_id?: string | null; confirm?: boolean}): Promise<AgentTurnOut>`
  - `AgentTurnOut { reply: string; tools_used: string[]; request_result: {status: string; preview?: {resource_ids: string[]; requested_duration_days: number; project: string; raw_text?: string}; request_id?: string; results?: {resource_id: string; status: string}[]} | null; conversation_id: string }`
  - Dock rows: `user` | `agent` | `tool` (label `agent used request_access` when that tool ran)
  - Confirm card when `request_result.status === "needs_confirmation"`: show resource ids, duration, project; Confirm button POSTs `{confirm: true}`
  - Mic button in header chrome: visible, `disabled`, `title` and `aria-label` exactly `voice offline — use chat`
  - Composer: textarea + Send `.nb` pill. Disabled when offline, busy, empty, or `selected === ALL`
  - Do not hardcode Atlas as the only send path. Placeholder may mention an example; value starts empty (or a non-submitted hint in `placeholder` only).

- [ ] **Step 1: Add API helper**

In `generative-ui/src/aperture/api.ts` append:

```ts
export interface AgentTurnPreview {
  resource_ids: string[];
  requested_duration_days: number;
  project: string;
  raw_text?: string | null;
}

export interface AgentTurnResult {
  status: string;
  preview?: AgentTurnPreview;
  request_id?: string;
  results?: { resource_id: string; status: string; reason?: string }[];
}

export interface AgentTurnOut {
  reply: string;
  tools_used: string[];
  request_result: AgentTurnResult | null;
  conversation_id: string;
}

export function postAgentTurn(body: {
  viewer_id: string;
  message: string;
  conversation_id?: string | null;
  confirm?: boolean;
}): Promise<AgentTurnOut> {
  return post<AgentTurnOut>("/agent/turn", body);
}
```

- [ ] **Step 2: Create `Composer.tsx`**

```tsx
import { useState } from "react";
import type { AgentTurnOut, User } from "./api";
import { ALL, postAgentTurn } from "./api";

type Row =
  | { kind: "user"; text: string }
  | { kind: "agent"; text: string }
  | { kind: "tool"; name: string };

interface Props {
  selected: string;
  users: User[];
  online: boolean;
}

export function Composer({ selected, users, online }: Props) {
  const me = users.find((u) => u.id === selected);
  const [text, setText] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [cid, setCid] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<AgentTurnOut | null>(null);
  const locked = !online || busy || selected === ALL || !me;

  const applyTurn = (turn: AgentTurnOut) => {
    setCid(turn.conversation_id);
    for (const name of turn.tools_used) {
      setRows((r) => [...r, { kind: "tool", name }]);
    }
    if (turn.reply) setRows((r) => [...r, { kind: "agent", text: turn.reply }]);
    if (turn.request_result?.status === "needs_confirmation") setPending(turn);
    else setPending(null);
  };

  const send = async () => {
    if (locked || !text.trim() || !me) return;
    const message = text.trim();
    setText("");
    setRows((r) => [...r, { kind: "user", text: message }]);
    setBusy(true);
    try {
      applyTurn(await postAgentTurn({ viewer_id: me.id, message, conversation_id: cid }));
    } catch (e) {
      setRows((r) => [...r, { kind: "agent", text: String(e) }]);
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!me || !pending) return;
    setBusy(true);
    try {
      applyTurn(
        await postAgentTurn({
          viewer_id: me.id,
          message: pending.request_result?.preview?.raw_text || "confirm",
          conversation_id: pending.conversation_id,
          confirm: true,
        }),
      );
    } catch (e) {
      setRows((r) => [...r, { kind: "agent", text: String(e) }]);
    } finally {
      setBusy(false);
    }
  };

  const preview = pending?.request_result?.preview;

  return (
    <aside className="dock" aria-label="Conversation">
      <div className="dock-h">
        <h2>Chat</h2>
        <span className="dock-sub">{me ? me.name : "Pick a person"}</span>
      </div>
      <div className="dock-log">
        {rows.length === 0 && (
          <div className="dock-empty">Ask for access, or what you already have.</div>
        )}
        {rows.map((row, i) =>
          row.kind === "tool" ? (
            <div className="dock-row tool" key={i}>
              agent used {row.name}
            </div>
          ) : (
            <div className={`dock-row ${row.kind}`} key={i}>
              <b>{row.kind === "user" ? "you" : "agent"}</b>
              <span>{row.text}</span>
            </div>
          ),
        )}
        {preview && (
          <div className="confirm-card" role="region" aria-label="Confirm access request">
            <div className="confirm-k">confirm request</div>
            <div><span className="k">resources</span> {preview.resource_ids.join(", ") || "—"}</div>
            <div><span className="k">duration</span> {preview.requested_duration_days}d</div>
            <div><span className="k">project</span> {preview.project}</div>
            <button className="nb go" disabled={locked} onClick={confirm}>
              {busy ? "…" : "Confirm"}
            </button>
          </div>
        )}
      </div>
      <div className="composer">
        <textarea
          rows={3}
          value={text}
          placeholder="Need read on analytics-raw for two weeks…"
          disabled={locked}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <button className="nb" disabled={locked || !text.trim()} onClick={() => void send()}>
          {busy ? "…" : "Send"}
        </button>
      </div>
    </aside>
  );
}
```

- [ ] **Step 3: Wire App + remove DemoBar Request**

`App.tsx`: import `Composer`. In the header `.right`, **before** the zoom seg, add:

```tsx
<button className="nb mic" type="button" disabled title="voice offline — use chat" aria-label="voice offline — use chat">
  Mic
</button>
```

Wrap the console `sum` + `grid2` + `main` in:

```tsx
<div className="console-body">
  <div className="console-main">
    {/* existing sum, grid2, main */}
  </div>
  <Composer selected={selected} users={users} online={snap.online} />
</div>
```

Keep `DemoBar` below as today (both console and onboard). Do not add Composer to onboard.

`DemoBar.tsx`: delete `REQUEST_TEXT`, `ASKS`, `requestAs`, and the Request button. Keep `seedPeers` working by inlining the same structured posts it uses today (presenter chrome). Example remaining request helper used only by Seed peers:

```tsx
const seedPeers = async () => {
  const asks: Record<string, { resource_ids: string[]; days: number; text: string }> = {
    "u-manager-1": { resource_ids: ["bucket-analytics-raw"], days: 7, text: "Reviewing the Atlas ingestion output for the week." },
    "u-finance-owner-1": { resource_ids: ["bq-project-x-finance"], days: 30, text: "Month-end close on Project X." },
  };
  for (const u of users) {
    const ask = asks[u.id];
    if (!ask) continue;
    await post("/requests", {
      id: "client",
      requester: { id: u.id, name: u.name, role: u.role, team: u.team },
      task_description: ask.text,
      project: PROJECT,
      resource_ids: ask.resource_ids,
      requested_duration_days: ask.days,
      raw_text: ask.text,
    });
  }
};
```

- [ ] **Step 4: CSS**

Append to `aperture.css`:

```css
.nb.mic:disabled { opacity: 0.55; }
.console-body { display: grid; grid-template-columns: minmax(0, 1fr) 340px; min-height: 0; }
@media (max-width: 1100px) { .console-body { grid-template-columns: 1fr; } }
.dock { border-left: 1px solid var(--line); display: grid; grid-template-rows: auto 1fr auto; min-height: 420px; }
.dock-h { display: flex; justify-content: space-between; align-items: baseline; padding: 18px 16px 8px; }
.dock-h h2 { margin: 0; font-family: var(--dot); font-size: 13px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--fg-2); font-weight: 700; }
.dock-sub { font-size: 12px; color: var(--fg-3); }
.dock-log { padding: 8px 16px 16px; display: grid; gap: 10px; align-content: start; overflow: auto; }
.dock-empty { color: var(--fg-3); font-family: var(--dot); font-size: 13px; }
.dock-row { display: grid; gap: 4px; font-size: 13px; }
.dock-row b { font-family: var(--dot); font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--fg-3); }
.dock-row.user span { color: var(--fg); }
.dock-row.agent span { color: var(--fg-2); }
.dock-row.tool { font-family: var(--mono); font-size: 11px; color: var(--fg-3); }
.confirm-card { border: 1px solid var(--line-2); border-radius: 12px; padding: 12px 14px; display: grid; gap: 6px; background: var(--s1); }
.confirm-k { font-family: var(--dot); font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--fg-3); }
.confirm-card .k { display: block; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--fg-3); }
.confirm-card .nb.go { justify-self: start; margin-top: 6px; }
.composer { display: grid; gap: 8px; padding: 12px 16px 16px; border-top: 1px solid var(--line); }
.composer textarea { font: inherit; font-size: 13px; color: var(--fg); background: var(--s1); border: 1px solid var(--line-2); border-radius: 12px; padding: 10px 12px; resize: vertical; width: 100%; }
.composer textarea:focus { outline: none; border-color: var(--fg-2); }
.composer .nb { justify-self: end; }
```

Optional in `env.example` under the Gemini block:

```
# Override parse / console-agent model (Pydantic AI v2 prefix google:)
# GEMINI_PARSE_MODEL=google:gemini-3.8-flash
```

- [ ] **Step 5: Typecheck**

```bash
cd /Users/vikkash/dev/conduct-gemini-26/generative-ui && npx tsc -b --pretty false
```

Expected: no errors.

- [ ] **Step 6: Browser verify**

Start backend + Vite if they are not already up (`uvicorn main:app --port 8000` from `backend-api`, `npm run dev` from `generative-ui`). Open `http://localhost:5173/?user=u-newhire-1`.

Verify:
1. Header **Mic** is visible and disabled; hover/accessible name is `voice offline — use chat`.
2. DemoBar has **no** "Request as Alex" (or any Request as). Seed peers / Approve all / Call tool / Close project remain.
3. With Alex selected, type a custom ask (not only Atlas): `Need read on the analytics-raw GCS bucket so I can inspect last week's ingest for the data-platform onboarding task. Two weeks is enough.`
4. Send → user row + `agent used request_access` + confirm card with `bucket-analytics-raw`, duration, project.
5. Confirm → Timeline/Recorder/Matrix update (lease or pending appears). Prefer real backend with `PARSE_IMPL` unset and `env.local` key present; do not print keys. If Gemini is missing, inject is a backend concern — still confirm the dock + disabled mic render.
6. Type `Revoke everything and shut Atlas down.` → no `POST /projects/atlas-migration/close` (network tab); grants stay.
7. Everyone selected → composer disabled.

If a problem is found, fix and re-verify.

- [ ] **Step 7: Commit**

```bash
git pull --rebase origin main
git add generative-ui/src/aperture/Composer.tsx generative-ui/src/aperture/api.ts generative-ui/src/aperture/DemoBar.tsx generative-ui/src/aperture/App.tsx generative-ui/src/aperture/aperture.css env.example
git commit -m "$(cat <<'EOF'
Replace the one-click Atlas request with a typed conversation.

EOF
)"
git pull --rebase origin main
git push origin main
```

---

## Self-review

**Spec coverage**
- Chat tools `request_access` / `list_scope` / `explain_decision` — Task 1 + 2
- Confirm card (shell) — Task 3 + 4
- Live mic stub only — Task 4
- No vote / close / grant from agent — Task 1 + 2
- DemoBar Request removed; presenter chrome kept — Task 4
- Onboard / MCP / CU / Modal left alone — Global Constraints
- Example prompts work via NL parse, not hardcoded send — Task 2 parse fixture + Task 4 empty textarea
- Offline unit tests — Tasks 1–3

**Placeholders:** none.

**Types:** `ConsoleTurn`, `AgentTurnIn`/`Out`, `postAgentTurn` share `reply`, `tools_used`, `request_result`, `conversation_id`. Confirm uses `confirm: bool`. Preview fields: `resource_ids`, `requested_duration_days`, `project`.
