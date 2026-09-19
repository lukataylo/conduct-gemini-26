# generative-ui

**Owner: contributor 1.** Renders whatever `backend-api` says the viewer is allowed to
see — as a live dashboard whose *shape* is composed by Gemini, not by frontend routing.
Design brief with every surface and its options: [`docs/ui-surfaces.html`](../docs/ui-surfaces.html)
(surfaces 1, 2, 4, 5, 6, 8).

## Ambition ladder

| | What | Done when |
|---|---|---|
| **Core** (must demo) | Registry renderer fed by SSE. Chat input → confirmation card. **Approver view with a vote button** (doesn't exist yet — first thing after SSE). Approval card: reason string as the summary on day one, requester text in a labelled unverified block, critical-tier justification. Per-request timeline with verify. Policy table. Denied panel. | Golden path from the browser including the approval. Close project → panel leaves live. |
| **Ambitious** (after 16:00) | Gemini emits **A2UI** against our catalog; client diffs on `panel.id` (in schema) and patches; data streams without regenerating layout. Then **role-adaptive composition**. Reviewed: with a three-component catalog this looks identical to the fallback — only build it once the catalog is wide enough to differ. | Same request, three viewers, three compositions, no flicker. |
| **Fallback** (in repo) | Static shell, state-driven panels from `/ui-spec`, 3s poll, `hasOwn` lookup, per-panel error boundary. | Already works. |

## Why A2UI

It's Google's own protocol (co-built with the Gemini Enterprise team), the judges are
from DeepMind, and it's the exact pattern the industry converged on: the agent sends a
JSON component tree plus a separate data model; the client renders only components in
its catalog. Spec: https://a2ui.org (v0.9 stable, v1.0 RC). We don't need the full
protocol — the message shape (`components[]` + `dataModel`) and the catalog idea are
enough. Keep our `UISpec`/`UIComponentSpec` as the wire type; make it A2UI-shaped.

## What's here (runnable now)

- `src/types.ts` — hand-mirrored `UISpec` types from `shared/schemas.py`.
- `src/registry.tsx` — `COMPONENT_REGISTRY`; unknown names render `UnknownComponent`
  instead of crashing. **Keep this.** It's the safety net once Gemini names components.
- `src/components/` — `GrantCard`, `PendingApprovalCard`, `AuditTimeline` stub.
- `src/App.tsx` — polls `/api/ui-spec/:requesterId` and renders through the registry.

## Build order

1. **SSE** — replace the 3s poll with `EventSource('/api/stream')` (contributor 5 ships
   it first). Panels update on `ui_spec` events; audit timeline on `audit_event`.
2. **Approver view** — a role picker (sets `X-Actor`), `GET /escalations?status=pending`,
   vote button posting `ApprovalVote` with `X-Demo-Key`. Then the chat input +
   confirmation card for the requester side.
3. **Approval card** — props: engine reason (the summary until Gemini's lands), tier,
   requester + team + manager, current holdings, peer comparison string, proposed expiry.
   Requester text only inside a quoted `RequesterClaim` block labelled "unverified
   requester text", truncated. Approve/deny are static chrome at the bottom, never
   catalog entries. Critical tier: approve disabled until `justification` is non-empty.
4. **Per-request timeline** — group `/audit?request_id=` events; reason strings and
   vote comments inline; a "verify chain" control calling `/audit/verify`;
   `ACTION_EXECUTED` events with a `screenshot_url` render as a filmstrip.
5. **Denied panel** — fixed position, reason string, alternative text if present.
6. **Policy table** — read `GET /policy`; sliders `PATCH /policy`; re-submit button.
7. **A2UI generation** (stretch) — `GET /ui-spec/:id?mode=generated` returns Gemini's
   spec (contributor 2 owns the prompt; you own the renderer). Diff by `panel.id`; CSS
   transitions on add/remove; never replace the tree wholesale.
8. **Role-adaptive** (stretch) — `?role=requester|approver|auditor`; three prompt variants.

## Rules that don't bend

- The deny control is never positioned by the model. Fixed slot, always visible.
- Every generated button carries an `action_id`; the server re-checks policy on it.
- Off-catalog component → `UnknownComponent`, visibly. Test the registry, not the model.

```bash
cd generative-ui && npm install && npm run dev   # proxies /api → localhost:8000
```
