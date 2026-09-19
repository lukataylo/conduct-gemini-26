# generative-ui

**Owner: contributor 1.** Renders whatever `backend-api`'s `/ui-spec/{requester_id}`
returns — a list of `{component, props}` panels — as a live dashboard. The generative
part is that the *set and shape* of panels comes from the server (ultimately Gemini),
not from the frontend's own routing/state logic.

## What's here (already runnable)

- `src/types.ts` — hand-mirrored `UISpec`/`UIComponentSpec` TS types matching
  `shared/schemas.py`.
- `src/registry.tsx` — `COMPONENT_REGISTRY`: maps a panel's `component` string to an
  actual React component. Unrecognized components fall back to `UnknownComponent`
  instead of crashing the page — important once Gemini is generating these names, since
  a bad generation shouldn't take the whole dashboard down.
- `src/components/` — `GrantCard`, `PendingApprovalCard` (both match what
  `backend-api`'s current static `/ui-spec` implementation emits — verified working end
  to end), and an `AuditTimeline` stub.
- `src/App.tsx` — polls `/api/ui-spec/:requesterId` every 3s and renders panels through
  the registry. Requester id is hardcoded to `usecase-demo`'s seed requester for now.

## Setup

```bash
cd generative-ui
npm install
npm run dev
# separately, in backend-api: uvicorn main:app --reload --port 8000
```

The dev server proxies `/api/*` to `localhost:8000` (see `vite.config.ts`) so no CORS
juggling is needed locally.

## Next steps for contributor 1

1. Run it against `backend-api` after contributor 5 wires up the golden-path scenario —
   confirm the bucket grant panel and the dataset "pending approval" panel both show up.
2. Build a second view for approvers (Priya/Jordan in the demo script) — a queue of
   pending `EscalationCase`s with the agent's reasoning and approve/deny buttons, posting
   to `POST /escalations/{id}/vote`.
3. Add more component types as `backend-api`'s `/ui-spec` grows (audit timeline is
   stubbed, add a "request submitted, awaiting parse" loading state, etc.) — coordinate
   new `component` names with contributor 5 so both sides agree on the prop shape.
4. Once contributor 2's Gemini UI-generation is live (replacing backend-api's static
   `/ui-spec` mapping), the registry is the safety net — make sure `UnknownComponent`
   renders something reasonable on stage rather than a blank panel.
5. Swap the 3s poll for SSE/websocket if there's time — nicer for the live "watch it
   update" demo moment.
