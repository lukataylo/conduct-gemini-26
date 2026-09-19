# Aperture console and the agent's MCP server — what's built, why, how

Status on `main` as of 19 Sep 2026, ~14:00. Everything below is runnable now against
the in-repo backend. This doc exists so the other tracks know what to build against, and
why it's shaped this way.

## The three screens (revised 19 Sep, 14:15)

The app is three screens for three people, plus a deep-dive. Switch with the header
nav or `?screen=onboard|me|manager|console`, and act as a person with `?user=`.

| Screen | For | What it shows | File |
|---|---|---|---|
| **Onboard** | the new hire | greeting, the one-line `claude mcp add …` for their agent, "or ask here", where they stand (active / waiting on whom), the three findings that motivate the product | `Onboard.tsx` |
| **My access** | the end user | a *generated* summary: headline ("you can use N things until …"), one guide card per active grant (what it is, a real command, the docs link, time left), pending cards (who's deciding, ✓ as votes land), refused cards with an alternative, and the exact `tools/list` their agent sees. Uses `/ui-spec` when a composer produced rich panels, else a deterministic fallback with the same vocabulary (`AccessSummary`, `ResourceGuide`, `PendingCard`, `DeniedCard`). Provenance line says which. An example is delivered as a Claude artifact: `docs/alex-access-summary.html` | `Summary.tsx` |
| **Manager** | the approver | every person as a row — colour, counts, a *mini* lease timeline, current resources — click to open their full timeline; the approval cards (Deny/Approve, real votes); a read-only policy pane (mirrors `DEFAULT_POLICY`, live when `/policy` ships); a Gemini dock on `POST /agent/turn` with the mic slot reserved for Gemini Live (track 2) | `Manager.tsx` |
| **Timeline** | deep-dive | the full console: stats, dot-matrix access grid, approvals, lease Gantt, recorder | `App.tsx` (console branch) |

## What exists

| Piece | Where | State |
|---|---|---|
| Requester/approver **console** (Leases timeline, Recorder, person switcher, dot-matrix access grid, Approvals panel) | `generative-ui/src/aperture/` | Working, polls the hub every 1.5 s |
| **Onboarding** view (connect command, NL request, live `tools/list`, evidence) | `generative-ui/src/aperture/Onboard.tsx` | Working |
| **MCP server** the coding agent connects through | `agent-runtime/mcp_serve.py` (uses `agent-runtime/mcp_server.py`) | Verified end to end over stdio |
| Backend reads the UI and MCP server need | `backend-api/main.py`: `GET /grants?include_revoked=true`, `GET /resources`, `GET /people`, `GET /tools?requester_id=` | Additive, no behaviour change elsewhere |
| Design briefs | `docs/ui-surfaces.html` (surfaces, trade-offs, build order), `docs/ui-directions.html` (four visual concepts) | Published |

Run it:

```bash
# terminal 1
cd backend-api && pip install -r requirements.txt && uvicorn main:app --port 8000
# terminal 2
cd generative-ui && npm install && npm run dev        # http://localhost:5173  (proxies /api → :8000)
# terminal 3 — the agent's side
pip install -r agent-runtime/requirements.txt          # pins mcp>=1.10,<2
claude mcp add aperture -e APERTURE_REQUESTER=u-newhire-1 -e APERTURE_BACKEND=http://127.0.0.1:8000 -- python agent-runtime/mcp_serve.py
```

Useful URLs: `/?user=u-manager-1` opens as Priya; `/?view=onboard` opens the onboarding
view; `?user=all` is the everyone view.

## Why it's shaped this way

Three reviews and two surveys fed this (see `docs/ui-surfaces.html` for the full
trail). The decisions that matter to other tracks:

1. **The agent's tool list is the UI.** Every access product surveyed shows the human
   a table and shows the agent nothing. Our thesis, and the one demo beat we protect, is
   *close the project and the tool vanishes from the agent's session*. So the MCP
   server derives `tools/list` from live grants and pushes `tools/list_changed` on
   change. The onboarding view shows the same list to humans, from the same backend
   derivation (`GET /tools`), so what the audience sees is exactly what Claude Code sees.

2. **Policy runs twice, and the second time is at the tool call.** The engine decides
   at request time. The MCP server re-fetches active grants on *every* call and refuses
   anything without one, writing `ACTION_EXECUTED` with `payload.status = "bounced"`.
   That bounce is the evidence we point at when a judge asks "what stops a generated
   button / a stale tool from doing something it shouldn't." The console draws it as a
   red diamond in the leases row, a red cell in the access grid, and a red row in the
   recorder.

3. **Time is the picture, not rows.** Standing privilege (access nobody revoked when
   the project ended) is the #1 audit finding in the industry research. A Gantt of
   leases makes expiry visible by construction: every grant is a bar that ends, pending
   is dashed, a revoke is a cut with a red cap. Zoom "session" is a live window that
   grows during the demo (minute-long leases stay readable); "project" is 16 days.

4. **Approval fatigue is fixed on the card, not in a workflow.** Research: >95% of
   entitlements get rubber-stamped in <10 s because the approver sees an entitlement
   string and nothing else. Our card carries the engine's reason, who already holds the
   resource, who decides alongside you, and the requester's text only as a claim. Deny
   and Approve are static chrome, never generated.

5. **One colour per person; red means refused.** Alex green, Priya violet, Jordan
   orange, assigned in `/people` order. Red is never a person. This is what makes the
   dot-matrix grid legible at a glance (a shared bucket splits diagonally between two
   people's colours).

6. **Everything the console shows is derived from the audit log and grants** — no
   UI-only state. If it isn't in `/audit`, `/grants`, or `/escalations`, it isn't on
   screen. That keeps the console honest and makes the chain-verify dot in the header
   meaningful.

## Implementation details

### Console (`generative-ui/src/aperture/`)

- `api.ts` — hand-mirrored types from `shared/schemas.py`; `useSnapshot()` polls
  `/grants?include_revoked=true`, `/escalations`, `/audit`, `/resources`, `/people`,
  `/audit/verify` every 1.5 s. Swap to `EventSource('/api/stream')` when track 5 ships
  SSE — the hook is the only place to change. `toUsers()` assigns colours.
- `App.tsx` — header (brand, person switcher, chain dot, session/project zoom,
  console/onboard view), summary strip, then `Matrix` + `Approvals` side by side,
  `Timeline`, `Recorder`, `DemoBar`. `--accent` and `--u` CSS variables carry the
  selected person's colour down the tree.
- `Timeline.tsx` — bars from grants (active: `granted_at → expires_at`; revoked:
  `granted_at → revoked_at`), pending cases (`opened_at → now`, dashed), and
  `request_denied` events (short red stub). Tool-call markers from `action_executed`
  events; `payload.status === "bounced"` renders as a red diamond. Window: session =
  `[first event − 2 min, now + 4 min]`, minimum 10 min; project = 16 days.
- `Matrix.tsx` — 36 time buckets × (resources + `calls` + `refused`). A cell's fills
  are the people holding that resource in that bucket (alpha = coverage); two people
  → diagonal split; pending → dashed cell in the requester's colour; denied/bounced →
  red cell. Rows come from `/resources`, so adding a resource to the seed adds a row.
- `Approvals.tsx` — cases where the selected person is a required approver who hasn't
  voted → bold card with `escalation_reason` (falls back to the `escalated` audit
  event's detail), requester, duration, tier/owning team, *also held by* (other people's
  active grants on that resource), *with you* (other required approvers, ✓ if voted).
  Deny/Approve `POST /escalations/{id}/vote` with `approver_id = selected person`. A
  requester sees "waiting on …" for their own pending cases. Everyone view: "Pick a
  person to decide."
- `Recorder.tsx` — `/audit` newest first, filtered to the selected person (actor, or a
  request/grant of theirs), each row with its `prev_hash` prefix. `action_executed`
  rows show "authorised by <resource> · <grant id>" or the bounce text.
- `Onboard.tsx` — step 1: the `claude mcp add` command for the selected person; step
  2: `POST /requests` with `{raw_text, requester_id}` (Gemini path); if that fails
  (no key on the machine) it falls back to a structured request with resource ids
  matched by keyword and says so; shows decision time and one row per resource; step
  3: `GET /tools?requester_id=` polled every 1.5 s. Evidence cards are static copy.
- `DemoBar.tsx` — presenter controls acting *as the selected person*: request, seed
  peers (Priya and Jordan file their own requests so the grid has three colours),
  approve all pending (votes as each required approver), call a tool (writes an
  `action_executed` event, bounced if no active grant), close project. Every button
  hits the real backend; nothing is faked client-side.
- `aperture.css` — Nothing-style: pure black, Doto (dot-matrix) for numerals, labels
  and headlines, Geist for body, IBM Plex Mono for ids. Fonts load from Google Fonts
  with system fallbacks. Semantic colours: green active, amber pending, red refused.

### MCP server (`agent-runtime/mcp_serve.py`)

- stdio transport, `mcp` 1.x low-level `Server` API (`@server.list_tools`,
  `@server.call_tool`). `mcp` 2.x renamed the API; `requirements.txt` pins `<2`.
- Config by env: `APERTURE_BACKEND` (default `http://127.0.0.1:8000`),
  `APERTURE_REQUESTER` (default `u-newhire-1`), `APERTURE_TOKEN` (sent as a bearer
  header; the backend doesn't enforce it yet — track 5 item), `APERTURE_POLL` seconds.
- `list_tools`: `request_access` + `my_access` always, plus
  `mcp_server.tools_for_grants(active grants)` — the teammate's allowlist
  (`gcs_list_analytics_raw`, `bq_query_project_x_finance`; `sql-prod-primary` is never
  exposed). The backend's `GET /tools` calls the same function, so UI and agent agree.
- `call_tool`: `request_access` posts NL to `/requests` and falls back to a keyword
  parse when the Gemini path returns non-200. Derived tools re-fetch grants, refuse if
  the tool isn't in the live set (bounce logged), otherwise return mock data and log an
  `ACTION_EXECUTED` ok.
- A background task polls grants and calls `session.send_tool_list_changed()` when the
  tool-name set changes. The session is captured on the first `list_tools` request.
- Verified with an MCP client over stdio: request → tool appears → call ok → approval
  → second tool appears → close project → both gone → retry refused and recorded →
  chain ok.

### Backend additions (`backend-api/main.py`)

- `GET /grants?include_revoked=true` — all grants for the timeline (default behaviour
  unchanged: active only, which is what the MCP server uses).
- `GET /resources`, `GET /people` — the catalog and the known requesters, for rows and
  the person switcher.
- `GET /tools?requester_id=` — `tools_for_grants(active_grants)`.

## Conventions other tracks should follow

- **`ACTION_EXECUTED` payload**: `{"tool": "<name>", "status": "ok" | "bounced",
  "requester_id": "<id>"}`. `grant_id` set when authorised, `null` when bounced. The
  console keys on `payload.status` and `payload.tool`; computer-use events can add
  `screenshot_url` and the recorder will pick it up later.
- **New resources**: add to `usecase-demo/seed_data.py` and to
  `agent-runtime/mcp_server.TOOL_SPECS` if the agent should get a tool for it.
- **New people**: add to `KNOWN_REQUESTERS`; they get the next palette colour.
- **Deny / Approve are never generated** — if `compose_ui` produces an approver
  layout, leave the decision controls to the static shell (`Approvals.tsx`).
- **Don't fake state in the UI**. Presenter controls go through the API so the audit
  chain shows them.

## Open items, by owner

- Track 5: `/stream` (SSE) — replace the poll in `api.ts`; `X-Demo-Key`/`X-Actor`
  enforcement (the vote endpoint already rejects non-required approvers); demo clock
  so "advance 14 days" works on stage; bearer tokens for the MCP server.
- Track 2: point `request_access` at the Modal parse endpoint once deployed; Gemini
  summaries into `EscalationCase.human_summary` (the card already prefers
  `escalation_reason`, add `human_summary` as the first line when present).
- Track 3: the chaining check — when it lands, its `request_denied` reason shows on
  the onboarding rows and the red cell in the grid without UI changes.
- Track 4: the second scenario's request text; a `/demo` route if the demo bar isn't
  enough.
- Track 1 (next): approver card counter-offer (shorter duration), role-adaptive layout
  once `compose_ui` is stable, SSE.
