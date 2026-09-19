# generative-ui

**Owner: contributor 1.** The human console. Gemini composes a **per-viewer
workspace** (analytics, quick actions, chat, Gemini Live) from that person's
role and live grants. It does not decide access. Finished-product spec:
[`docs/superpowers/specs/2026-09-19-generative-console-design.md`](../docs/superpowers/specs/2026-09-19-generative-console-design.md).
Surface options: [`docs/ui-surfaces.html`](../docs/ui-surfaces.html)
(surfaces 1, 2, 4, 5, 6, 8).

The shell is static (role, Live mic, conversation dock, approver vote chrome).
Gemini fills MAIN and the action strip against the catalog. Chat and Live are
one conversation hosted by track 2; they can `request_access` and explain, they
cannot vote or grant.

## Ambition ladder

| | What | Done when |
|---|---|---|
| **Core** (must demo) | Registry renderer fed by SSE. Chat input → confirmation card. **Approver view with a vote button** (doesn't exist yet — first thing after SSE). Approval card: reason string as the summary on day one, requester text in a labelled unverified block, critical-tier justification. Per-request timeline with verify. Policy table. Denied panel. | Golden path from the browser including the approval. Close project → panel leaves live. |
| **Ambitious** (after the 16:00 checkpoint) | Per-viewer **generative console** from the spec: analytics widgets (`ScopeMap`, `LeaseGantt`, `QueueSLA`, …), server-issued quick actions, chat + **Gemini Live** as one agent. A2UI-shaped `UISpec` with `region` / `role` / `actions`; client diffs on `panel.id`. Same grants, Alex vs Priya are different trees. | Switch role and the workspace recomposes; Live answers "what's waiting?" from typed state; mic-down still leaves the canvas usable. |
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
7. **Generative console** (stretch, after checkpoint) — implement the catalog
   and shell in the [console spec](../docs/superpowers/specs/2026-09-19-generative-console-design.md):
   analytics widgets, `QuickActionBar`, conversation dock, Live mic. `GET /ui-spec/:id?mode=generated&role=`
   returns track 2's `compose_console`. Diff by `panel.id`; never replace the tree wholesale.
8. **Chat + Gemini Live** (stretch) — one `conversation_id`; Live hosted by track 2
   on the AI Studio key. Vote and grant stay out of the tool list.

## Rules that don't bend

- The deny control is never positioned by the model. Fixed slot, always visible.
- Every generated button carries an `action_id`; the server re-checks policy on it.
- Off-catalog component → `UnknownComponent`, visibly. Test the registry, not the model.

```bash
cd generative-ui && npm install && npm run dev   # proxies /api → localhost:8000
```
