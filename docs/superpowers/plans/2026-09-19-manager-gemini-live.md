# Manager Gemini Live Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Aperture Live bubble a conversational Gemini (text + Live audio) that knows actor, focus, and page; can sponsor access through policy; and can start request-specific Computer Use on GCP or SAP using the focused person’s grant — without ever writing a Grant or voting.

**Architecture:** `POST /agent/turn` stays the text path. It sends `viewer_id` (actor), `focus_id`, `page`, and a stored transcript. The console agent gains `request_access_for` and `enact`. `enact` calls `_enqueue_execute(grant, action, ask=)` so Computer Use goals include the human sentence. Native Live is a later session on the same `conversation_id` and tools. Policy stays in `policy-engine`; the hub only omits a sponsor from `required_approver_ids`.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, Pydantic AI, pytest, React 18, Vite, existing Aperture CSS, Gemini Computer Use (`computer_use.py`), mock consoles `:8765` / `:8766`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-19-manager-gemini-live-design.md`. Follow it when a task and the spec disagree on product behaviour.
- LLMs never write a `Grant`. No chat-started CU `grant` or `revoke`. No vote tools. Approve / Deny stay `Approvals.tsx`.
- `POST /agent/turn` keeps `viewer_id` as actor. Add optional `focus_id` and `page`. Do not rename `viewer_id`.
- `sql-prod-primary` and `sap-hr-payroll` stay in `NEVER_ENACT_IDS`. `sap-customer-directory` is never granted; only `action=export` may enqueue to show the bounce (`grant_id` null).
- JIT-Evidence-01: do not overwrite a ticket the client sent. Default `ATLAS-142` only when missing. SAP `INC-8841` stays when present.
- `REAL_GCP` unused by the console agent. No `google-cloud-*` from chat.
- Do not rewrite `mcp_serve.py` / `tools_for_grants`. Do not resurrect registry `App.tsx`.
- Do not commit `env.local`, `.env`, keys, or recordings.
- Unit tests offline: inject `AGENT_TURN_IMPL`, `PARSE_IMPL`, `EXECUTE_ENQUEUE_IMPL`. Live Gemini / Live audio are optional smokes, never required in pytest.
- Existing `tests/test_engine.py` Atlas and SAP golden cases stay green. Add new engine tests; do not edit those assertions.
- Existing `backend-api/tests/test_agent_turn.py` confirm / steal-confirm / SQL escalate paths stay green.
- Work on `feat/enactment-platform`. One concern per commit; message is why. Never force-push. Never `--no-verify`.
- Do not name a new function `_console_role` — that name already means GCP IAM display strings in `main.py`. Use `_viewer_console_role`.
- Do not stage unrelated dirty WIP (`policy_final_story.py`, uncommitted SAP HTML) unless the task lists that file.

## File map

- Modify: `agent-runtime/console_agent.py`
- Modify: `agent-runtime/tests/test_console_agent.py`
- Modify: `policy-engine/engine.py`
- Create: `tests/test_platform_routes.py`
- Modify: `backend-api/main.py`
- Modify: `backend-api/tests/test_agent_turn.py`
- Modify: `backend-api/tests/test_enqueue.py`
- Modify: `agent-runtime/computer_use.py`
- Modify: `agent-runtime/tests/test_computer_use.py`
- Modify: `agent-runtime/gemini_models.py`
- Create: `agent-runtime/live_session.py`
- Create: `agent-runtime/tests/test_live_session.py`
- Modify: `generative-ui/src/aperture/api.ts`, `App.tsx`, `Menu.tsx`, `Live.tsx`, `Manager.tsx`, `Users.tsx`, `aperture.css`

Do not modify: `mcp_serve.py`, `mcp_server.py` `TOOL_SPECS`, `tests/test_engine.py` assertion bodies.

---

### Task 1: Console agent context, sponsor, and enact tools

**Files:**
- Modify: `agent-runtime/console_agent.py`
- Modify: `agent-runtime/tests/test_console_agent.py`

**Interfaces:**
- Consumes: existing `Requester`, `run_console_turn(message, deps, *, runner, conversation_id)`
- Produces:
  - `LEGAL_TOOLS = ("request_access", "list_scope", "explain_decision", "request_access_for", "enact")`
  - `ILLEGAL_TOOLS` unchanged (`grant`, `vote`, `close_project`, `patch_policy`)
  - `class ConsoleContext(BaseModel): actor_id: str; focus_id: str | None = None; page: str = "overview"; role: str = "user"`
  - `def build_system_prompt(ctx: ConsoleContext | None, actor: Requester | None = None, focus_name: str | None = None) -> str`
  - `ConsoleAgentDeps` gains optional `request_access_for: Callable[[str, str], dict]`, `enact: Callable[[str, str, str | None], dict]`, `context: ConsoleContext | None = None`, `history: list[dict]`, `focus: Requester | None = None`
  - `ConsoleTurn` gains `enact_result: dict | None = None`
  - `default_console_runner` registers the two new tools; uses `build_system_prompt` when `deps.context` is set
  - `run_console_turn` calls `run(message, deps, build_system_prompt(deps.context, deps.viewer, deps.focus.name if deps.focus else None))`

- [ ] **Step 1: Write the failing tests**

Replace `test_legal_tools_are_exactly_the_three` and add tests. Keep existing request/refuse/list tests working by giving `_deps()` default no-op callables for the new fields.

```python
from console_agent import (
    ILLEGAL_TOOLS,
    LEGAL_TOOLS,
    SYSTEM_PROMPT,
    ConsoleContext,
    build_system_prompt,
)

def test_legal_tools_include_sponsor_and_enact():
    assert "request_access_for" in LEGAL_TOOLS
    assert "enact" in LEGAL_TOOLS
    for name in ILLEGAL_TOOLS:
        assert name not in LEGAL_TOOLS


def test_system_prompt_still_refuses_illegal_verbs():
    lowered = SYSTEM_PROMPT.lower()
    for name in ILLEGAL_TOOLS:
        assert name in lowered
    assert "never grant" in lowered or "must not grant" in lowered
    built = build_system_prompt(
        ConsoleContext(actor_id="u-manager-1", focus_id="u-finance-owner-1", page="overview", role="manager"),
        actor=Requester(id="u-manager-1", name="Priya Nair", role="Engineering Manager", team="data-platform"),
        focus_name="Jordan Lee",
    ).lower()
    assert "priya nair" in built
    assert "jordan lee" in built
    assert "overview" in built
    assert "request_access_for" in built
    assert "enact" in built
    for name in ILLEGAL_TOOLS:
        assert name in built


def test_request_access_for_and_enact_do_not_write_grants():
    seen: list[tuple] = []

    def request_access_for(beneficiary_id: str, raw_text: str) -> dict:
        seen.append(("sponsor", beneficiary_id, raw_text))
        return {"status": "needs_confirmation", "preview": {"beneficiary_id": beneficiary_id}}

    def enact(action: str, raw_text: str, resource_id: str | None = None) -> dict:
        seen.append(("enact", action, raw_text, resource_id))
        return {"status": "enqueued", "action": action}

    def runner(message, deps, system_prompt):
        assert "priya" in system_prompt.lower()
        if "grant jordan" in message.lower():
            payload = deps.request_access_for("u-finance-owner-1", message)
            return ConsoleTurn(reply="Confirm sponsoring Jordan.", tools_used=["request_access_for"], request_result=payload)
        payload = deps.enact("query", message, "bq-project-x-finance")
        return ConsoleTurn(reply="Looking at finance.", tools_used=["enact"], enact_result=payload)

    deps = _deps(request_access_for=request_access_for, enact=enact)
    deps.context = ConsoleContext(actor_id="u-manager-1", focus_id="u-finance-owner-1", page="timeline", role="manager")
    deps.focus = Requester(id="u-finance-owner-1", name="Jordan Lee", role="Finance Data Owner", team="finance")
    deps.viewer = Requester(id="u-manager-1", name="Priya Nair", role="Engineering Manager", team="data-platform")

    turn = run_console_turn("grant Jordan read on analytics-raw for Atlas", deps, runner=runner)
    assert turn.tools_used == ["request_access_for"]
    assert seen[0][0] == "sponsor"
    assert "Grant(" not in str(turn.request_result)

    turn2 = run_console_turn("invoice lines in finance", deps, runner=runner)
    assert turn2.tools_used == ["enact"]
    assert turn2.enact_result["status"] == "enqueued"
```

Update `_deps` so missing new callables default to no-ops.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/vikkash/dev/conduct-gemini-26
PYTHONPATH=agent-runtime:. python -m pytest agent-runtime/tests/test_console_agent.py -v
```

Expected: FAIL — `request_access_for` / `enact` / `build_system_prompt` / `ConsoleContext` missing.

- [ ] **Step 3: Write minimal implementation**

In `console_agent.py` add `ConsoleContext`, `build_system_prompt`, extend `LEGAL_TOOLS` and `SYSTEM_PROMPT` (keep illegal verbs; add request_access_for and enact; say never enact grant/revoke). Extend `ConsoleAgentDeps` and `ConsoleTurn`. Register tools in `default_console_runner`. Prepend last 20 history lines to the **model** message only, not to tool raw_text. `run_console_turn` uses `build_system_prompt(...)`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=agent-runtime:. python -m pytest agent-runtime/tests/test_console_agent.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent-runtime/console_agent.py agent-runtime/tests/test_console_agent.py
git commit -m "$(cat <<'EOF'
Tell the console agent who it is talking to before it chooses a tool.

EOF
)"
```

Do not stage other dirty files.

---

### Task 2: Platform metadata and SAP company-code deny

**Files:**
- Modify: `policy-engine/engine.py` — `_peer_metadata`, `_surface_decision`, `_gcp_decision`, `_sap_decision`
- Create: `tests/test_platform_routes.py`

**Interfaces:**
- `_peer_metadata` sets `metadata["platform"]` to `"sap"` for SAP_* types else `"gcp"`. For SAP, copy `role`, `company_code`, `customer_id`, `activity` from `resource.metadata` when present.
- `def _gcp_decision(...) -> PolicyDecision | None` returns `None` (does not short-circuit Atlas).
- `_surface_decision` calls `_gcp_decision` for GCS_BUCKET, BIGQUERY_DATASET, CLOUD_SQL_INSTANCE.
- `_sap_decision`: if `resource.metadata.get("company_code") == "2000"`, deny with reason containing `company 2000`. Keep Conduct-SAP-01 for directory/payroll.

- [ ] **Step 1: Write failing tests** in `tests/test_platform_routes.py` (copy helpers from `tests/test_engine.py`; do not edit `test_engine.py` assertions).
  - GCP bucket same-team internal auto-grant has `metadata.platform == "gcp"`
  - GCP finance cross-team escalates and `platform == "gcp"`
  - SAP directory still AUTO_DENY Conduct-SAP-01 and `platform == "sap"`
  - SAP BP with `company_code: "2000"` is AUTO_DENY and reason contains `2000`

- [ ] **Step 2:** `PYTHONPATH=policy-engine:. python -m pytest tests/test_platform_routes.py -v` Expected FAIL.

- [ ] **Step 3:** Implement `_peer_metadata` tags, `_gcp_decision` returns None, company 2000 deny.

- [ ] **Step 4:** `PYTHONPATH=policy-engine:. python -m pytest tests/test_platform_routes.py tests/test_engine.py -v` Expected PASS.

- [ ] **Step 5:** Commit only those two files. Message: `Tag policy decisions with the platform they apply to.`

---

### Task 3: Hub context, history, list_scope queue, policy routes

**Files:**
- Modify: `backend-api/main.py`
- Modify: `backend-api/tests/test_agent_turn.py`

**Interfaces:**
- `AgentTurnIn.focus_id: str | None = None`, `page: str = "overview"`
- `AgentTurnOut.enact_result: dict | None = None`, `navigate: str | None = None`
- `def _viewer_console_role(viewer: Requester) -> str` — regex `manager|owner|lead|head` → `"manager"` else `"user"`
- `def _resolve_person(raw: str) -> Requester | None`
- `CONVERSATIONS[id]` includes `messages` and `actor_id`
- `_console_list_scope(viewer, *, focus=None)` returns `{grants, cases, waiting_on_me, focus_grants, focus_cases}` — `grants`/`cases` stay actor-as-requester
- `waiting_on_me` = pending where `viewer.id in required_approver_ids`
- History last 20 sent on deps; store last 40
- If `slot["actor_id"]` differs from viewer, mint a new conversation_id
- `GET /policy/routes` → `{"gcp": [{"id","name","approver_ids"}], "sap": [...]}` (`sap-*` vs rest)

Keep existing confirm / steal-confirm / list_scope actor tests green.

- [ ] **Step 1:** Add tests `test_list_scope_as_priya_includes_waiting_on_me`, `test_history_is_stored_and_actor_change_resets_conversation`, `test_policy_routes_split_gcp_and_sap`.
- [ ] **Step 2:** Run `test_agent_turn.py` — FAIL.
- [ ] **Step 3:** Implement helpers and wire `agent_turn` + `GET /policy/routes`.
- [ ] **Step 4:** `test_agent_turn.py` + `test_audit_post.py` PASS.
- [ ] **Step 5:** Commit. Message: `Give the manager agent the queue it is actually looking at.`

Do not stage unrelated dirty `main.py` hunks that are not part of this task — if `main.py` already has local WIP, keep those lines but only commit if they are required; prefer not to include `policy_final_story`.

---

### Task 4: Sponsor through policy (no silent grant)

**Files:**
- Modify: `backend-api/main.py`
- Modify: `backend-api/tests/test_agent_turn.py`

**Interfaces:**
- `_console_request_access_for(raw_text, actor, beneficiary, *, evaluate, conversation_id)`
- Parse as beneficiary. Preview includes `beneficiary_id`, `sponsored_by=actor.id`
- Confirm allowed when `pending.requester.id == viewer.id` OR `pending.metadata.sponsored_by == viewer.id`
- `_evaluate_request`: REQUEST_RECEIVED actor = sponsor or requester; payload `beneficiary_id` when sponsored
- Escalation approvers: omit sponsor; if that empties the list, keep original (`filtered or approvers`)

Tests: sponsor Jordan bucket → grant.requester_id is Jordan, audit actor Priya; sponsor finance omits Priya from required approvers; sponsor directory denied, no grant.

- [ ] Steps: TDD then commit: `Let a manager sponsor someone else’s request without minting the grant.`

---

### Task 5: Hub enact → enqueue with the ask

**Files:**
- Modify: `backend-api/main.py`
- Modify: `backend-api/tests/test_agent_turn.py`
- Modify: `backend-api/tests/test_enqueue.py`
- Modify: `backend-api/tests/conftest.py` — clear `ENACT_RUNNING`

**Interfaces:**
- `_CHAT_ENACT_ACTIONS = frozenset({"browse", "query", "inspect", "export"})`
- `_REFUSE_ENACT_IDS = frozenset({"sql-prod-primary", "sap-hr-payroll"})`
- `_console_enact(...)` statuses: `refused`, `need_focus`, `no_grant`, `running`, `enqueued`
- `export` on `sap-customer-directory` does not require a grant; synthetic Grant not persisted; `grant_id` null; `_enqueue_execute` allows this when `action=="export"` despite NEVER_ENACT
- `_enqueue_execute(grant, action="grant", ask=None)` forwards `ask`
- `AgentTurnOut.navigate` = `"timeline"` when enact enqueued
- `ENACT_RUNNING` one run per grant id

Tests: no grant → no enqueue; Jordan finance grant + query ask enqueued; SQL refused; enqueue test forwards ask.

Seed Jordan finance with `main._issue_grant` after setting `EXECUTE_ENQUEUE_IMPL`. Clear `seen` before the chat enact.

- [ ] Commit: `Start computer use from chat only when the focused person already has a lease.`

---

### Task 6: Computer Use follows the ask

**Files:**
- Modify: `agent-runtime/computer_use.py`
- Modify: `agent-runtime/tests/test_computer_use.py`

**Interfaces:**
- `browse_goal`/`query_goal`/`inspect_goal`/`enact_goal` take optional `ask`
- With `ask=None`, `enact_goal(grant, "browse") == browse_goal(grant)` still holds
- With ask set, goal string contains the ask
- `verify_browse` / `verify_query` / `verify_inspect` — browse is NOT `verify_active`
- `_verify_page` dispatches by action
- `run_computer_use_loop` and `execute_grant` take `ask`
- Playwright fallback `_playwright_read` for browse/query/inspect/export using existing data-* selectors

- [ ] Commit: `Steer computer use with the sentence the human actually said.`

If local uncommitted SAP CU changes exist in `computer_use.py`, keep them and add `ask` on top. Do not revert SAP goals.

---

### Task 7: Actor vs focus chrome, Live context, watch, policy panel

**Files:**
- Modify: `generative-ui/src/aperture/api.ts`, `App.tsx`, `Menu.tsx`, `Users.tsx`, `Live.tsx`, `Manager.tsx`, `aperture.css`

**Interfaces:**
- Manager: `actorId` (signed-in as, default Priya) separate from `scope`/`focusId` (cards + chips, default ALL)
- PersonMenu manager lists only `roleOf === "manager"` (Priya + Jordan owner). Label `signed in as`
- Cards/chips set focus only
- Live props: `viewer` (actor), `focus`, `page`, `onNavigateTimeline`
- `postAgentTurn` sends `viewer_id`, `focus_id`, `page`
- Subtitle: `as {actor} · looking at {focus|everyone}`
- Reset conversation only when actor.id changes
- `navigate === "timeline"` → switch to Timeline, set focus
- Manager policy: fetch `/api/policy/routes`, two tables plus existing tier table

- [ ] `npx tsc -b --pretty false` must pass.
- [ ] Commit: `Stop the manager dropdown from changing who Gemini thinks it is.`

---

### Task 8: Conversational Live audio (same thread)

**Files:**
- Modify: `agent-runtime/gemini_models.py`
- Create: `agent-runtime/live_session.py`
- Create: `agent-runtime/tests/test_live_session.py`
- Modify: `backend-api/main.py` — `POST /agent/live/session`
- Modify: backend tests
- Modify: `Live.tsx`, `api.ts`

**Interfaces:**
- `DEFAULT_LIVE_MODEL = "gemini-2.5-flash-native-audio"`
- `def live_model() -> str`
- `start_live_session(context, conversation_id) -> {ok, conversation_id, model, fallback}`
  - no key → `ok: False`, `fallback: "speech"`
  - key present → `ok: True`, never include the API key in the dict
- `POST /agent/live/session` body `{viewer_id, focus_id?, page?, conversation_id?}`
- `LIVE_SESSION_IMPL` injectable
- Live.tsx: on open POST session; keep same `conversation_id`; if both Live and SpeechRecognition missing, title `voice offline — use chat`
- Do not reset cid when toggling mic; new session only when actor changes

CI does not require a Gemini Live WebRTC handshake.

- [ ] Commit: `Open a Live session on the same conversation the text bubble already uses.`

---

## Self-review

Tasks 1–7 produce a demo-ready text bubble. Task 8 adds the Live session pin. Native Live WebRTC can attach to `ok: true` later without changing tools.
