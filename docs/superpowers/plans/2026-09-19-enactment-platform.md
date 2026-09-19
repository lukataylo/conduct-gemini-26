# Enactment Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the pushed policy engine into the hub, then expand the mock GCP console and Computer Use so grants and revokes are enacted on a richer console.

**Architecture:** `LIVE_POLICY` is the only `PolicyRule` the hub evaluates against. `_evaluate_request` attaches demo ticket `ATLAS-142` when business context is missing, then calls `policy_engine.evaluate_request(..., policy=LIVE_POLICY, active_grants=..., now=now())`. Later tasks add console state, SSE, clock, and CU verbs. The engine itself is not edited.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, pytest, Playwright, existing `policy-engine` / `shared.schemas`.

## Global Constraints

- LLMs never write a Grant. CU only enacts an existing grant or revoke.
- Do not edit `policy-engine/engine.py` or `tests/test_engine.py`.
- `evaluate_request` is called with `policy=LIVE_POLICY`, `active_grants=active_grants(requester.id)`, `now=now()`.
- JIT-Evidence-01: `_evaluate_request` attaches `context.active_jira_ticket=ATLAS-142` (or `APERTURE_TICKET`) when the request has no ticket/incident. Existing client tickets are kept.
- `GET /grants` default stays active + unexpired.
- `sql-prod-primary` never appears in `TOOL_SPECS` / MCP.
- `ACTION_EXECUTED` convention in `docs/console-and-mcp.md` stays; additive payload keys only.
- `REAL_GCP` stays grant/revoke IAM only; mock console data is fake.
- Do not commit `env.local`, `.env`, keys, or recordings.
- `mcp` pin stays `<2`. Do not rewrite `mcp_serve.py`.
- Do not edit `generative-ui/`.
- Work on branch `feat/enactment-platform`. One concern per commit; message is why, not what.
- Tests must not call the live Gemini API.

## File map

- Modify: `backend-api/main.py` — `LIVE_POLICY`, `_ensure_business_context`, `GET /policy`, later stream/clock/console/enqueue
- Create: `backend-api/tests/test_policy.py`
- Modify: `backend-api/tests/conftest.py` — reset `LIVE_POLICY`
- Modify: `backend-api/tests/test_agent_turn.py` only if a test still fails after hub ticket attach
- Modify: `agent-runtime/mock_console/index.html`
- Modify: `agent-runtime/tests/test_mock_console.py`
- Modify: `agent-runtime/computer_use.py`
- Modify: `agent-runtime/tests/test_computer_use.py`
- Create: `backend-api/tests/test_console_state.py`, `test_stream.py`, `test_clock.py`

---

### Task 1: Integrate the pushed policy engine in the hub

**Files:**
- Modify: `backend-api/main.py`
- Create: `backend-api/tests/test_policy.py`
- Modify: `backend-api/tests/conftest.py`

**Interfaces:**
- Consumes: `policy_engine.DEFAULT_POLICY`, `policy_engine.evaluate_request`, `AccessContext`, `PolicyRule`
- Produces: `LIVE_POLICY: PolicyRule`, `DEMO_TICKET: str`, `_ensure_business_context(request: AccessRequest) -> AccessRequest`, `GET /policy -> PolicyRule`

- [ ] **Step 1: Write the failing tests**

Create `backend-api/tests/test_policy.py`:

```python
from fastapi.testclient import TestClient

import main
from shared.schemas import AccessContext, AccessRequest, DecisionType


def test_get_policy_returns_live_default():
    client = TestClient(main.app)
    resp = client.get("/policy")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == main.LIVE_POLICY.id
    assert body["description"] == main.policy_engine.DEFAULT_POLICY.description
    assert "internal" in body["max_auto_grant_duration_days"]


def test_evaluate_uses_live_policy_and_attaches_demo_ticket():
    alex = main.KNOWN_REQUESTERS["u-newhire-1"]
    request = AccessRequest(
        id="ignored",
        requester=alex,
        task_description="need analytics-raw",
        project="atlas-migration",
        resource_ids=["bucket-analytics-raw"],
        requested_duration_days=14,
        raw_text="need analytics-raw",
    )
    assert not request.context.active_jira_ticket
    out = main._evaluate_request(request)
    assert out["results"][0]["status"] == "granted"
    stored = main.REQUESTS[out["request_id"]]
    assert stored.context.active_jira_ticket == "ATLAS-142"


def test_evaluate_keeps_caller_ticket():
    alex = main.KNOWN_REQUESTERS["u-newhire-1"]
    request = AccessRequest(
        id="ignored",
        requester=alex,
        task_description="need analytics-raw",
        project="atlas-migration",
        resource_ids=["bucket-analytics-raw"],
        requested_duration_days=14,
        context=AccessContext(active_jira_ticket="ATLAS-999"),
    )
    out = main._evaluate_request(request)
    stored = main.REQUESTS[out["request_id"]]
    assert stored.context.active_jira_ticket == "ATLAS-999"
    assert out["results"][0]["status"] == "granted"


def test_evaluate_passes_live_policy(monkeypatch):
    seen = {}

    def fake_evaluate(request, resources, policy=None, active_grants=None, now=None, **kw):
        seen["policy"] = policy
        seen["now"] = now
        seen["grants"] = list(active_grants or [])
        from shared.schemas import PolicyDecision

        return [
            PolicyDecision(
                request_id=request.id,
                resource_id="bucket-analytics-raw",
                decision=DecisionType.AUTO_GRANT,
                reason="stub",
                ttl_hours=24,
            )
        ]

    monkeypatch.setattr(main.policy_engine, "evaluate_request", fake_evaluate)
    alex = main.KNOWN_REQUESTERS["u-newhire-1"]
    request = AccessRequest(
        id="ignored",
        requester=alex,
        task_description="need analytics-raw",
        project="atlas-migration",
        resource_ids=["bucket-analytics-raw"],
        requested_duration_days=14,
    )
    main._evaluate_request(request)
    assert seen["policy"] is main.LIVE_POLICY
    assert seen["now"] is not None
```

In `backend-api/tests/conftest.py`, after the existing clears, reset policy:

```python
    main.LIVE_POLICY = main.policy_engine.DEFAULT_POLICY.model_copy(deep=True)
```

Add the same assignment at the start of `reset_store` (before yield) and after yield.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend-api && PYTHONPATH=.:.. pytest tests/test_policy.py -v`

Expected: FAIL — `LIVE_POLICY` missing and/or `GET /policy` 404

- [ ] **Step 3: Write minimal implementation**

In `backend-api/main.py`:

1. Import `PolicyRule` from `shared.schemas` (keep existing imports).
2. After `KNOWN_REQUESTERS`:

```python
LIVE_POLICY: PolicyRule = policy_engine.DEFAULT_POLICY.model_copy(deep=True)
DEMO_TICKET = os.environ.get("APERTURE_TICKET", "ATLAS-142")


def _has_business_context(request: AccessRequest) -> bool:
    ctx = request.context
    meta = request.metadata or {}
    return bool(
        ctx.active_jira_ticket
        or ctx.active_pagerduty_incident
        or meta.get("ticket_id")
        or meta.get("incident_id")
    )


def _ensure_business_context(request: AccessRequest) -> AccessRequest:
    """Demo default for JIT-Evidence-01. Keep an explicit caller ticket/incident."""
    if _has_business_context(request):
        return request
    return request.model_copy(
        update={"context": request.context.model_copy(update={"active_jira_ticket": DEMO_TICKET})}
    )
```

3. At the top of `_evaluate_request`, after looking up `requester` and before assigning `id`:

```python
    request = _ensure_business_context(request)
```

4. Change the `evaluate_request` call to:

```python
    decisions = policy_engine.evaluate_request(
        request,
        resources,
        policy=LIVE_POLICY,
        active_grants=active_grants(requester.id),
        now=now(),
    )
```

5. Add:

```python
@app.get("/policy")
def get_policy() -> PolicyRule:
    return LIVE_POLICY
```

Do not change engine files. Do not add PATCH.

- [ ] **Step 4: Run tests**

Run:

```
cd backend-api && PYTHONPATH=.:.. pytest tests/test_policy.py tests/test_agent_turn.py tests/test_audit_post.py tests/test_cu_frames.py -v
cd .. && PYTHONPATH=. pytest tests/test_engine.py -q
```

Expected: all PASS. Agent-turn bucket grant still works because `_evaluate_request` now attaches `ATLAS-142`.

- [ ] **Step 5: Commit**

```bash
git add backend-api/main.py backend-api/tests/test_policy.py backend-api/tests/conftest.py
git commit -m "$(cat <<'EOF'
Evaluate requests against the live policy and demo ticket.

EOF
)"
```

---

### Task 2: Mock console revoke + hash routes

**Files:**
- Modify: `agent-runtime/mock_console/index.html`
- Modify: `agent-runtime/tests/test_mock_console.py`

**Interfaces:**
- Consumes: existing grant dialog, `#active-grants`, permissions tables
- Produces: hash routes `#storage/bucket-analytics-raw/permissions`, `#bigquery/bq-project-x-finance/permissions`, `#iam`; Remove button `data-action="revoke"` `data-resource` `data-principal`; confirm dialog `aria-label="Confirm revoke"`; granted rows also in `#active-grants`

- [ ] **Step 1: Extend `test_mock_console.py`**

Assert these strings exist in `index.html`: `data-action="revoke"`, `Confirm revoke`, `#storage/bucket-analytics-raw/permissions` (as a documented route in a comment or `data-hash-example` attribute on `<html>`: `data-hash-example="#storage/bucket-analytics-raw/permissions"`), and JS functions that parse `location.hash`.

Also assert `Apply hash` is not required as visible text. Required labels: `Remove`, `Confirm revoke`.

```python
def test_console_has_revoke_and_hash_hooks():
    text = HTML.read_text()
    assert 'data-action="revoke"' in text
    assert 'aria-label="Confirm revoke"' in text
    assert 'data-hash-example="#storage/bucket-analytics-raw/permissions"' in text
    assert "location.hash" in text
    assert "Remove" in text
```

- [ ] **Step 2: Run to verify fail**

`cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_mock_console.py::test_console_has_revoke_and_hash_hooks -v`

Expected: FAIL

- [ ] **Step 3: Implement**

On `<html>` add `data-hash-example="#storage/bucket-analytics-raw/permissions"`.

When a grant is confirmed, append a permissions `<tr>` that includes:

```html
<button type="button" class="btn" data-action="revoke" data-resource="..." data-principal="...">Remove</button>
```

Add `#revoke-dialog` with button `aria-label="Confirm revoke"`. Confirm removes the matching `#active-grants` `<li>` and the permissions row.

Parse hash on load and `hashchange`:

- `#storage` / `#storage/<id>/<tab>`
- `#bigquery` / `#bigquery/<id>/<tab>` (`query` tab opens dataset + compose later; for this task map `query` to `permissions` if compose is missing)
- `#sql` / `#sql/<id>/<tab>`
- `#iam`

`setView` / `openResource` should `history.replaceState` the matching hash.

Keep existing Grant access / Confirm / `#active-grants` behavior unchanged.

- [ ] **Step 4: Run** `cd agent-runtime && PYTHONPATH=.:.. pytest tests/test_mock_console.py -v` — PASS

- [ ] **Step 5: Commit** `git commit` with message `Let the mock console revoke a principal and deep-link a resource.`

---

### Task 3: Mock console objects preview + query editor

**Files:**
- Modify: `agent-runtime/mock_console/index.html`
- Modify: `agent-runtime/tests/test_mock_console.py`

**Interfaces:**
- Produces: object row `data-object="events/2026-09-18.parquet"` (add this object to the Objects table; keep existing jsonl rows); `#object-preview` with `data-object` set on click; `#query-editor`, `#query-run`, `#query-results` with `data-dataset="bq-project-x-finance"` after Run.

- [ ] **Step 1: Test**

```python
def test_console_has_object_preview_and_query():
    text = HTML.read_text()
    assert 'data-object="events/2026-09-18.parquet"' in text
    assert 'id="object-preview"' in text
    assert 'id="query-editor"' in text
    assert 'id="query-run"' in text
    assert 'id="query-results"' in text
    assert 'data-dataset="bq-project-x-finance"' in text
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

Add parquet row to Objects. Clicking a `data-object` row shows `#object-preview` (not hidden) and sets `data-object`. COMPOSE A NEW QUERY / Sharing stay. Add a `data-tab="query"` on the dataset view (or a compose panel) with textarea `#query-editor`, button `#query-run` labeled `Run`. Clicking Run sets `#query-results` `data-dataset="bq-project-x-finance"` and fills a small fake table (`events_raw` count `184221`). Hash `#bigquery/bq-project-x-finance/query` opens that tab. No live BigQuery.

- [ ] **Step 4: pytest `test_mock_console.py` PASS**

- [ ] **Step 5: Commit** `Add seeded object preview and a fake BigQuery run on the mock console.`

---

### Task 4: GET /console/state + hydrate

**Files:**
- Modify: `backend-api/main.py`
- Create: `backend-api/tests/test_console_state.py`
- Modify: `agent-runtime/mock_console/index.html`

**Interfaces:**
- Produces: `GET /console/state -> {resources: list[Resource], bindings: [{resource_id, principal, role, expires_at, grant_id}]}`
- Role map: `bucket-analytics-raw` → `Storage Object Viewer`; `bq-project-x-finance` → `BigQuery Data Viewer`; `sql-prod-primary` → `Cloud SQL Client`; GitHub repos → `Triage` (read) or `Write` (write capability). Only **active** grants.

- [ ] **Step 1: Test** issue a grant via `_evaluate_request` for the bucket, `GET /console/state`, assert one binding with `principal=u-newhire-1`, `role=Storage Object Viewer`, `resource_id=bucket-analytics-raw`.

- [ ] **Step 2: FAIL 404**

- [ ] **Step 3: Implement endpoint.** Console JS: if `URLSearchParams` has `backend` or `window.CONSOLE_BACKEND`, `fetch(backend + '/console/state')` and render bindings into permissions + `#active-grants`. On fetch fail, keep in-page state.

- [ ] **Step 4: `pytest tests/test_console_state.py tests/test_policy.py -v` PASS**

- [ ] **Step 5: Commit** `Expose console bindings from active grants.`

---

### Task 5: SSE stream + demo clock + enqueue revoke

**Files:**
- Modify: `backend-api/main.py`, `backend-api/requirements.txt` (add `sse-starlette>=2.0` if missing)
- Create: `backend-api/tests/test_stream.py`, `backend-api/tests/test_clock.py`
- Modify: `backend-api/tests/conftest.py` — reset `CLOCK_OFFSET` to `timedelta(0)`

**Interfaces:**
- `now()` returns `datetime.now(timezone.utc) + CLOCK_OFFSET`
- `POST /clock/advance` body `{days: int}` adds days, audits `actor="policy-engine"` detail `advanced {days}d`, returns `{now, offset_days}`
- Sweeper function `sweep_expired() -> list[str]` revokes active grants with `expires_at <= now()` reason `expired` and calls `_enqueue_execute(grant, action="revoke")`
- `GET /stream` uses `sse-starlette.EventSourceResponse`; subscribers receive JSON `{type, event}` where type is `audit_event` plus `grant_issued` / `grant_revoked` / `project_closed` when the audit type matches
- `_audit` publishes to in-process subscribers
- `_enqueue_execute(grant, action: str = "grant")` — store action; existing grant path unchanged; `revoke_grant` and `close_project` call it with `action="revoke"` after the grant is marked revoked
- Do not add X-Demo-Key. Do not switch Aperture off polling.

Tests: advance 14 days, grant that expires in 1 hour is still active before advance and revoked after sweep; stream test uses TestClient to POST /audit and read one SSE line if practical — otherwise unit-test the publisher list.

If `sse-starlette` is heavy for a unit test, implement a `STREAM_SUBSCRIBERS: list` and a `GET /stream` that iterates it; test by appending a list and calling `_audit`, asserting the list grew.

- [ ] Commit `Stream audit events and advance a demo clock that expires grants.`

---

### Task 6: Computer Use revoke + verify_inactive

**Files:**
- Modify: `agent-runtime/computer_use.py`
- Modify: `agent-runtime/tests/test_computer_use.py`

**Interfaces:**
- `revoke_goal(grant) -> str` must include resource id, principal, `Remove`, `Do not grant any other resource`
- `verify_inactive(html, grant) -> bool` True when no `data-resource`+`data-principal` pair matches
- `execute_grant(..., action: str = "grant")` — `action="revoke"` uses Playwright: open permissions, click `[data-action=revoke][data-principal=...]`, click Confirm revoke, then `verify_inactive`
- `completed_event` payload includes `"action": action` (default `"grant"`)
- Playwright test: grant then revoke against `serve_in_thread`

- [ ] Commit `Enact revokes on the mock console the same way we enact grants.`

---

### Task 7: Computer Use browse + query goals + enqueue action

**Files:**
- Modify: `agent-runtime/computer_use.py`
- Modify: `agent-runtime/tests/test_computer_use.py`
- Modify: `backend-api/main.py` `_enqueue_execute` already has `action` from Task 5

**Interfaces:**
- `browse_goal(grant) -> str` names `events/2026-09-18.parquet` and `#object-preview`
- `query_goal(grant) -> str` names `project-x-finance` and `#query-results`
- `enact_goal(grant, action: str) -> str` dispatches `grant|revoke|browse|query`
- Mocked `run_computer_use_loop` tests unchanged; add tests that `enact_goal` contains the right selectors
- `_enqueue_execute` passes `action` into `execute_grant(..., action=action)` on the local path

- [ ] Commit `Give computer use browse and query goals and honor enqueue action.`

---

## Self-review

- Spec coverage: policy live + ticket, GET /policy, console revoke/hash, objects/query, console/state, SSE+clock+revoke enqueue, CU revoke, CU browse/query.
- Engine files not in any task.
- Types: `LIVE_POLICY`, `_ensure_business_context`, `DEMO_TICKET=ATLAS-142`, `GET /policy`, `GET /console/state`, `sweep_expired`, `revoke_goal`, `verify_inactive`, `enact_goal`.
