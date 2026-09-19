# agent-runtime

**Owner: contributor 2.** Everything that touches a model or drives the console, on
**Modal**, instrumented with **Pydantic AI + Logfire**. Both are hackathon partners;
use them for what they're actually for. Design brief: [`docs/ui-surfaces.html`](../docs/ui-surfaces.html)
(surfaces 1, 3, 7).

## Ambition ladder

| | What | Done when |
|---|---|---|
| **Core** (must demo) | Gemini structured-output parse with resource ids as an **enum** (no hallucinated buckets). Pydantic AI agent wrapping it, `logfire.instrument_pydantic_ai()` on, every call traced. Gemini writes the approver-facing summary *from the structured `PolicyDecision`*, never from the requester's raw text. | Parse event in the audit trail links to its Logfire span. |
| **Ambitious** (wins) | **Computer use in a Modal Sandbox** driving the mock console — one recorded run in the afternoon, every screenshot + action stored as `ACTION_EXECUTED` events. **Scoped MCP server**: `tools/list` derived from the requester's active grants; `tools/list_changed` on revoke; Claude Code as the on-stage client. Gemini composes the A2UI spec for contributor 1. | Claude Code lists tools, calls one against the mock GCS, and loses it when the project closes. |
| **Fallback** | Recorded replay (already the default). Action log without images. | — |

## What's here

- `gemini_parser.py` — `parse_request()`; the `TODO` marks the `google-genai` call.
  Use `response_schema` with `resource_ids: list[Literal[...known ids...]]` built at
  call time from `known_resource_ids`.
- `computer_use.py` — `execute_grant()`; the `TODO` marks the computer-use loop.
  Start from Modal's official example: https://modal.com/docs/examples/anthropic_computer_use
- `audit_logger.py` — `log(...)`; call `set_emitter()` to POST to `backend-api /audit`.
- `modal_app.py` — endpoints for parse and execute.

## Build order

1. **Parse** — real Gemini call, enum-constrained. Return `AccessRequest`. Wrap in a
   Pydantic AI `Agent` with `output_type=AccessRequest`; `logfire.configure()` +
   `logfire.instrument_pydantic_ai()`. Put `trace_id` in `AuditEvent.payload`.
2. **Summaries** — `summarize_decision(decision, resource, requester) -> str` for the
   approval card. Input is the typed decision only. Fallback: the reason string.
3. **A2UI spec** — `compose_ui(grants, cases, role) -> UISpec` with a fixed catalog in
   the prompt and `response_schema=UISpec`. Contributor 1 renders it.
4. **Computer use** — Modal Sandbox + headless Chromium against the mock console URL
   (contributor 4). Goal derived from a `Grant`. Save each screenshot to a Modal Volume;
   emit `ACTION_EXECUTED` with `{"screenshot_url", "action"}`. Record once at ~16:30.
5. **Scoped MCP** — `mcp_server.py`: FastMCP; on `tools/list` query
   `GET /grants?requester_id=` and expose `gcs_list_objects`, `gcs_read_object`,
   `bq_query`, plus `request_access`. Tool descriptions written by Gemini from the grant
   (task, expiry). Subscribe to `/stream`; on `grant_revoked` send `tools/list_changed`.
6. **Live gate** — `execute_grant_endpoint` streams screenshots over SSE only if the
   18:30 rehearsal passed twice. Otherwise replay.

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
