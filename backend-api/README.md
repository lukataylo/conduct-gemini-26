# backend-api

**Owner: contributor 5.** The FastAPI hub — the only piece that talks to all four other
workstreams. Owns persistence (in-memory for the hackathon), the approval queue
endpoints, the audit trail, and deployment.

## Verified working (see below)

`main.py` already runs the full golden path end to end: submit a request → policy-engine
auto-grants the bucket + escalates the dataset → both owning-team approvers vote →
escalation resolves to `approved` → second grant issues → `/ui-spec` reflects both
grants. This was smoke-tested directly (not just import-checked) while scaffolding —
see the repo's commit history / ask contributor for the test snippet if useful as a
starting point for `tests/test_golden_path.py`.

## What's here

- `policy_engine_paths.py` — import shim. `policy-engine/` and `usecase-demo/` have
  hyphens in their folder names, so they can't be `import`ed normally; this loads their
  modules by file path. Use `from policy_engine_paths import policy_engine, escalation,
  usecase_demo` rather than reaching into those folders directly.
- `main.py` — endpoints:
  - `POST /requests` — submit a structured `AccessRequest`, get back per-resource
    grant/escalate/deny results.
  - `GET /escalations` / `POST /escalations/{id}/vote` — the approval queue.
  - `POST /grants/{id}/revoke` — manual or TTL-triggered revocation.
  - `GET /audit` — the full typed audit trail.
  - `GET /ui-spec/{requester_id}` — current `UISpec` for `generative-ui` to render.
    Currently a static mapping from grants/escalations to panels — **this is the seam
    to hand to Gemini** (contributor 1/2), see its docstring TODO.

## Known gaps / next steps for contributor 5

1. `POST /requests` currently accepts an already-structured `AccessRequest` — wire it up
   to call `agent-runtime`'s `parse_request` (via Modal endpoint or direct import) so it
   can also accept raw text, once contributor 2's Gemini call is live.
2. `_issue_grant()` has a `TODO` to call `agent-runtime`'s `execute_grant` (computer-use)
   — currently grants are issued silently. Decide sync vs. callback with contributor 2.
3. No TTL sweeper yet — add a background task (APScheduler, or a simple loop) that calls
   `revoke_grant()` on anything past `expires_at`, and/or a manual "close project"
   endpoint for the demo's step 8.
4. In-memory store resets on restart — fine for a demo, but add a `/seed` endpoint (or
   startup hook) that loads `usecase_demo.REQUESTER` / `RESOURCES` so the scenario is
   ready without manual setup before each run-through.
5. CORS is wide open (`allow_origins=["*"]`) — fine for a hackathon demo, tighten if
   this goes anywhere past that.

## Setup

```bash
cd backend-api
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# then: open http://localhost:8000/docs
```

## Deploy (Railway)

This project already has the Railway MCP/skill available — once `main.py` is stable,
provision a service, set env vars from `.env`, and point it at this folder.
