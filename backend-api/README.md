# backend-api

**Owner: contributor 5.** The hub every other track talks to. Owns state, the stream,
the approval endpoints, the audit spine, and deploy. Design brief:
[`docs/ui-surfaces.html`](../docs/ui-surfaces.html) (surfaces 6, 9, 10).

## Ambition ladder

| | What | Done when |
|---|---|---|
| **Core** (must demo) | Hardened hub (in repo, verified): server-assigned ids, requester lookup, approver-only votes, expiry enforced, hash-chained audit with `GET /audit/verify`, `GET /grants`, `POST /projects/{id}/close`. **SSE first, thirty minutes** — `/stream` emitting `ui_spec`, `audit_event`, `grant_revoked`; every track-1 item waits on it. `X-Demo-Key` on writes, `X-Actor` must match `approver_id` on votes. **Demo clock** with `POST /clock/advance`; TTL sweeper. **Railway deploy by 13:30** — the Modal Sandbox can't reach localhost. | Front end never polls. Close project → `grant_revoked` on the stream. Console has a public URL. |
| **Ambitious** (after 16:00) | `GET/PATCH /policy` with validation. Per-requester MCP bearer tokens at seed time. `ACTION_EXECUTED` ingest requires the runtime secret. Chain head into a Logfire span every N events. CORS restricted to the UI origin. | Tamper with one event in a shell, `/audit/verify` names the index. |
| **Fallback** | In-memory dicts (in repo). Full event-sourced fold was reviewed as a two-hour refactor for three seconds on stage — don't. | Already works. |

## What's here

- `main.py` — `POST /requests`, `GET /escalations`, `POST /escalations/{id}/vote`,
  `POST /grants/{id}/revoke`, `GET /audit`, `GET /ui-spec/{requester_id}`.
- `policy_engine_paths.py` — import shim for the hyphenated sibling folders.

## Build order

1. **SSE, first** — `/stream` via `sse-starlette`; in-process broadcast; publish after
   every state change (`_audit` is the natural hook). Contributor 1 switches immediately.
2. **Demo headers** — middleware: `X-Demo-Key` required on POST; on `/vote`, `X-Actor`
   must equal `vote.approver_id`. Ten lines. Seed a bearer token per requester for MCP.
3. **Deploy, by 13:30** — Railway service for this app + the mock console (contributor 4
   hands you the page); env from `.env`. Computer use and the MCP server need the URL.
4. **Clock + sweeper** — `clock.py` with a forward-only offset behind `now()`;
   `POST /clock/advance` (audited); background task every 2s revokes expired grants.
5. **Policy endpoints** — hold one `PolicyRule`; `GET /policy`; `PATCH` validates and swaps.
6. **Wire contributor 2** — `POST /requests` accepts `{"raw_text": ...}` and calls the
   Modal parse endpoint; `/grants/execute` for the console form; `ACTION_EXECUTED`
   ingest requires the runtime secret; `trace_id` passthrough.
7. **Anchor** — every 20 events, log the chain head to Logfire. Restrict CORS.

## Rules that don't bend

- The engine decides; this service records and executes. Never grant outside
  `_issue_grant`, never revoke outside `revoke_grant`, both always emit an event.
- Every generated action id is re-validated here before anything happens.

```bash
cd backend-api && pip install -r requirements.txt sse-starlette && uvicorn main:app --reload --port 8000
```
