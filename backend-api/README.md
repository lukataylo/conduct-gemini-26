# backend-api

**Owner: contributor 5.** The hub every other track talks to. Owns state, the stream,
the approval endpoints, the audit spine, and deploy. Design brief:
[`docs/ui-surfaces.html`](../docs/ui-surfaces.html) (surfaces 6, 9, 10).

## Ambition ladder

| | What | Done when |
|---|---|---|
| **Core** (must demo) | FastAPI hub (in repo, golden path verified). **SSE stream** `/stream` emitting `ui_spec`, `audit_event`, `grant_revoked`. Seed loader on startup. **Demo clock** — every time read goes through `clock.now()`, with `POST /clock/advance`. TTL sweeper. `POST /projects/{id}/close` bulk revoke. `GET/PATCH /policy`. | Front end never polls. Advancing the clock revokes on screen. |
| **Ambitious** (wins) | **Hash-chained, event-sourced store**: `AuditEvent.prev_hash`; grants and cases are a fold over the log; `GET /audit/verify` re-hashes and reports. Approver resolution and peer-comparison plumbing for the card. `trace_id` on model-produced events linking to Logfire. Railway deploy with a public URL for the mock console (computer use needs it). | "Verify chain" returns OK on stage; tamper with one event in a shell, it returns the index that broke. |
| **Fallback** | In-memory dicts (in repo). | Already works. |

## What's here

- `main.py` — `POST /requests`, `GET /escalations`, `POST /escalations/{id}/vote`,
  `POST /grants/{id}/revoke`, `GET /audit`, `GET /ui-spec/{requester_id}`.
- `policy_engine_paths.py` — import shim for the hyphenated sibling folders.

## Build order

1. **SSE** — `/stream` via `sse-starlette`; an in-process broadcast; publish after every
   state change. Contributor 1 switches to it immediately.
2. **Clock + sweeper** — `clock.py` with an offset; background task every 2s revokes
   expired grants and publishes `grant_revoked`.
3. **Close project** — revoke all grants whose request's `project` matches; one event
   per grant plus a `PROJECT_CLOSED` event (add to `AuditEventType`, additive).
4. **Policy endpoints** — hold one `PolicyRule`; `PATCH` validates via Pydantic and swaps.
5. **Event sourcing** — `store.py`: `append(event)` sets `prev_hash = sha256(prev)`;
   `state()` folds the log into grants/cases; `/audit/verify`. Do this before 16:00 or
   not at all — it's a two-hour refactor and everything else depends on the store.
6. **Wire contributor 2** — `POST /requests` accepts `{"raw_text": ...}` and calls the
   Modal parse endpoint; `_issue_grant` enqueues `execute_grant`; `/grants` for the MCP
   server; `/grants/execute` for the mock console form.
7. **Deploy** — Railway service for this + the console; env from `.env`.

## Rules that don't bend

- The engine decides; this service records and executes. Never grant outside
  `_issue_grant`, never revoke outside `revoke_grant`, both always emit an event.
- Every generated action id is re-validated here before anything happens.

```bash
cd backend-api && pip install -r requirements.txt sse-starlette && uvicorn main:app --reload --port 8000
```
