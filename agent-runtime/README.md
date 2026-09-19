# agent-runtime

**Owner: contributor 2.** Everything that touches a model or drives the console, on
**Modal**, instrumented with **Pydantic AI + Logfire**. Both are hackathon partners;
use them for what they're actually for. Design brief: [`docs/ui-surfaces.html`](../docs/ui-surfaces.html)
(surfaces 1, 3, 7).

**Shipping this session (track 2 owner):** parse + Logfire, **computer use must ship**,
and **A2UI `compose_ui`** for track 1. MCP stays in the team brief as a parallel
thesis; it does not replace those three. Plan:
[`docs/superpowers/plans/2026-09-19-agent-runtime-core.md`](../docs/superpowers/plans/2026-09-19-agent-runtime-core.md).

## Ambition ladder

| | What | Done when |
|---|---|---|
| **Core** (must demo) | **Scoped MCP server on Modal, from noon** — this is the thesis ("the agent's tool list is the UI"): `tools/list` from `GET /grants?requester_id=`; every handler re-checks the grant then logs `ACTION_EXECUTED`; `tools/list_changed` on `grant_revoked`; Claude Code as the client. Gemini structured-output parse with resource ids as an **enum**. Pydantic AI agent wrapping it, `logfire.instrument_pydantic_ai()` on. | Claude Code lists two tools, calls one, and loses it when the project closes — by 16:00, then rehearsed all afternoon. |
| **Ambitious** (after 16:00) | Gemini writes the approver summary *from the typed `PolicyDecision`* (never from requester text) and task-scoped tool descriptions. **Computer use in a Modal Sandbox** against the *deployed* console — one recorded run, screenshots as `ACTION_EXECUTED`. Reviewed as L, not M; only start it with the checkpoint passed. Gemini composes the A2UI spec for contributor 1. | A filmstrip in the timeline with capture times. |
| **Fallback** | Reason string as the summary. No computer use — the tool call *is* the enactment. | — |

## What's here

- `gemini_parser.py` — `parse_request()`; the `TODO` marks the `google-genai` call.
  Use `response_schema` with `resource_ids: list[Literal[...known ids...]]` built at
  call time from `known_resource_ids`.
- `computer_use.py` — `execute_grant()`; the `TODO` marks the computer-use loop.
  Start from Modal's official example: https://modal.com/docs/examples/anthropic_computer_use
- `audit_logger.py` — `log(...)`; call `set_emitter()` to POST to `backend-api /audit`.
- `modal_app.py` — endpoints for parse and execute.
- `mcp_server.py` — `tools_for_grants(grants)`: the allowlisted, grant-derived tool
  list (`sql-prod-primary` is never exposed). Pure function; the backend's `GET /tools`
  and the stdio server both call it.
- `mcp_serve.py` — **the running MCP server** (built 19 Sep, verified over stdio).
  `request_access` + `my_access` always; grant-derived tools appear/disappear with
  grants; every call re-checks the grant and logs `ACTION_EXECUTED` (`ok`/`bounced`);
  `tools/list_changed` is pushed when the grant set changes. Env: `APERTURE_BACKEND`,
  `APERTURE_REQUESTER`, `APERTURE_TOKEN`, `APERTURE_POLL`. Uses the `mcp` 1.x API —
  `requirements.txt` pins `mcp>=1.10,<2` (2.x renamed the server API). Connect with:
  `claude mcp add aperture -e APERTURE_REQUESTER=u-newhire-1 -- python agent-runtime/mcp_serve.py`.
  Details and conventions: [`docs/console-and-mcp.md`](../docs/console-and-mcp.md).

## Build order

1. **Scoped MCP, 12:00** — `mcp_server.py` with FastMCP, deployed on Modal. On
   `tools/list` query `GET /grants?requester_id=` (exists) and expose `gcs_list_objects`,
   `gcs_read_object`, `bq_query`, plus `request_access` (returns
   `{status, reason, alternatives}` on denial, never a bare error). Each handler
   re-fetches the grant, checks active + unexpired + resource match, acts against the
   mock layer, then POSTs `ACTION_EXECUTED`. Present a per-requester bearer token
   (contributor 5 issues them at seed time). Subscribe to `/stream`; on `grant_revoked`
   send `tools/list_changed`. Connect Claude Code on the presenter's laptop.
2. **Parse** — real Gemini call, enum-constrained. Wrap in a Pydantic AI `Agent` with
   `output_type=AccessRequest`; `logfire.configure()` + `logfire.instrument_pydantic_ai()`.
   Put the span id in `AuditEvent.trace_id` (field exists).
3. **Summaries + descriptions** — `summarize_decision(decision, resource, requester)`;
   input is the typed decision only. Tool descriptions from the grant (task, expiry).
   Fallback: the reason string.
4. **Computer use** (stretch) — Modal Sandbox + headless Chromium against the *deployed*
   console URL (contributor 5, by 13:30). Goal from the `Grant` only, turn budget, egress
   limited to that URL; afterwards diff console state against the grant, revert on
   mismatch. Screenshots to a Volume; `ACTION_EXECUTED` with `{"screenshot_url","action"}`.
5. **A2UI spec** (stretch) — `compose_ui(grants, cases, role) -> UISpec` with the
   catalog in the prompt and `response_schema=UISpec`; server drops panels whose ids
   aren't in the viewer's active set. Contributor 1 renders it.
6. **Live gate** — screenshots over SSE only if the 18:30 rehearsal passed twice.

## Rules that don't bend

- No model output ever becomes a grant. Parse → engine → grant. Summaries are prose.
- Resource ids are an enum in the schema. The task description is a string the engine
  never reads as instructions.
- Computer use *executes* an already-decided grant. It never decides.

```bash
cd agent-runtime && pip install -r requirements.txt
modal token new && modal secret create access-scope-agent-secrets GEMINI_API_KEY=... ANTHROPIC_API_KEY=... LOGFIRE_TOKEN=...
modal serve modal_app.py
```
