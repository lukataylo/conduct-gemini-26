# generative-ui

**Owner: contributor 1.** Renders whatever `backend-api` says the viewer is allowed to
see — as a live dashboard whose *shape* is composed by Gemini, not by frontend routing.
Design brief with every surface and its options: [`docs/ui-surfaces.html`](../docs/ui-surfaces.html)
(surfaces 1, 2, 4, 5, 6, 8).

## Ambition ladder

| | What | Done when |
|---|---|---|
| **Core** (must demo) | Registry renderer fed by SSE instead of polling. Context-rich approval card with tiered justification. Per-request audit timeline. Policy table. | Golden path runs from the browser end to end, no curl. |
| **Ambitious** (wins) | Gemini emits **A2UI** (Google's agent-driven UI protocol) against our catalog; client diffs panel ids and patches incrementally; data-model updates stream without regenerating layout. Then **role-adaptive composition**: intern / approver / auditor get different layouts from the same data. | A grant appears and a revocation removes a panel with no flicker and no lost scroll. Same request, three viewers, three compositions. |
| **Fallback** (in repo) | Static shell, state-driven panels from `/ui-spec`, 3s poll. | Already works. |

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

1. **SSE** — replace the 3s poll with `EventSource('/api/stream')` (contributor 5 is
   adding it). Panels update on `ui_spec` events; audit timeline on `audit_event`.
2. **Approval card** — props: engine reason, Gemini summary, tier, requester + team +
   manager, current holdings, peer comparison string, proposed expiry, task. Approve/deny
   fixed at the bottom. Critical tier: approve disabled until `justification` is
   non-empty; post it with the vote.
3. **Per-request timeline** — group `/audit?request_id=` events; render reason strings
   and vote comments inline; `ACTION_EXECUTED` events with a `screenshot` in payload
   render as a filmstrip.
4. **Policy table** — read `GET /policy`; sliders `PATCH /policy`; re-submit button.
5. **A2UI generation** — new `GET /ui-spec/:id?mode=generated` returns Gemini's
   A2UI-shaped spec (contributor 2 owns the prompt; you own the renderer). Diff by
   `panel.id`; CSS transitions on add/remove; never replace the tree wholesale.
6. **Role-adaptive** — pass `?role=requester|approver|auditor`; three prompt variants.

## Rules that don't bend

- The deny control is never positioned by the model. Fixed slot, always visible.
- Every generated button carries an `action_id`; the server re-checks policy on it.
- Off-catalog component → `UnknownComponent`, visibly. Test the registry, not the model.

```bash
cd generative-ui && npm install && npm run dev   # proxies /api → localhost:8000
```
