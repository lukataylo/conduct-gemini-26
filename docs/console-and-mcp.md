# Aperture console and the agent's MCP server — what's built, why, how

Status on `main` as of 19 Sep 2026, ~14:00. Everything below is runnable now against
the in-repo backend. This doc exists so the other tracks know what to build against, and
why it's shaped this way.

## Role, tabs, person (revised 19 Sep, 15:10)

Header, left to right: brand · **tabs for the current role** · chain status ·
**User | Manager** toggle · **person dropdown** (`Menu.tsx`, `PersonMenu`). Switching
role swaps the tabs and the people in the dropdown; the dropdown also holds the
presenter actions (Reset demo, Approve all, <person> uses a tool, Close project).
Role is derived from `Requester.role` (`roleOf`: manager / owner / lead / head →
manager; everyone else → user). `?role=user|manager&user=<id>` opens a state.

- **Manager tabs:** Overview (people cards + Add a person + approvals column) ·
  Timeline (Everyone or one person via chips). The manager dropdown lists everyone;
  picking a person scopes the Timeline.
- **User tabs:** Onboard (landing) · Access (generated summary) · Timeline (that person).
- **Both roles:** Policy (the scenario-driven policy demo, see the table below).
- **Person cards** are Nothing-style widget tiles: a white hero count (open leases), a
  ring dial in the person's colour (time left on the soonest lease), *until*, *waiting*
  (amber only when > 0, naming who), *refused* (red only when > 0), and dot-tick call
  activity over the last three hours. Zero states are dimmed so colour means something.
- **Gemini Live** is a bubble at the bottom right of every screen (`Live.tsx`) and the
  only chat: one conversation on `POST /agent/turn` as the current person, including
  the confirm-request flow. Voice in via Web Speech (Chrome/Safari), voice out via
  speech synthesis; a dot-matrix face (blinks, glances, spins while thinking, squints
  while speaking) and a dot-matrix waveform driven by the mic level. It explains and
  drafts; it cannot vote or grant.
- **Timeline layout:** Access grid and Leases stack in the main column; Approvals sit
  in the right column (where the chat composer used to be).
- **Model paths need keys:** `.env` (gitignored) with `GEMINI_API_KEY` and
  `LOGFIRE_TOKEN`; run `uvicorn main:app --env-file ../.env`. Natural-language asks go
  through Gemini structured output; chat goes through Pydantic AI with Logfire tracing.
  Without a key the console's Ask falls back to a local keyword parse and says so.

**Demo data is a morning of history, not an instant.** `POST /demo/seed` resets the
store and replays a scenario through the normal request / vote / revoke paths with the
clock wound back (6h ago Priya's task, later relinquished; 5h ago Jordan's month-end
access; 2h ago Alex's request — repo and bucket granted, dataset escalated, Jordan
approved, Priya pending; the agent's calls; one bounce; a critical-tier ask still
waiting). The console calls it once when the store is empty. Timestamps are real, so
the grid, leases and recorder have shape on first load.

| Screen | What it shows | File |
|---|---|---|
| **Overview** | left: one card per person — leases with time left, what's waiting and on whom, ended leases struck through, the agent's live tools, **Ask** / **Access →** / **Timeline →** — plus an **Add a person** card (`POST /people`); right: every open approval with **Approve · <next approver>** / **Deny** casting a real vote, the policy table, the Gemini dock | `Users.tsx`, `Manager.tsx` (`ManagerSide`), `Approvals.tsx` |
| **Onboard** | the new hire's landing page: dot-matrix greeting and thesis, a live dot-matrix *iris* that opens with their active leases, open/waiting/calls/until, then 1 connect (the `claude mcp add` line) · 2 ask · 3 use (status rows and the agent's tools), and the three findings | `User.tsx` |
| **My access** | the generated summary — headline, a guide card per grant (what it is, a real command, the docs link), waiting and refused cards, the agent's tools; `/ui-spec` when a composer produced rich panels, else the deterministic fallback | `Summary.tsx` |
| **Policy** | the Friday Finance Freeze, beat by beat: requester / resource / capability / context, the engine's exact reason, compliance breadcrumbs, the approver's evidence card, and the Reaper toggle for ATLAS-101 — all from `GET /demo/policy/final-story`, which runs the real engine on fixed inputs (no store, no model) and reports the doc's success criteria | `Policy.tsx`, `backend-api/policy_demo.py` |
| **Timeline** | deep-dive, Everyone or one person: stats, dot-matrix grid, approvals, lease Gantt, recorder, the Enact pane, the chat composer | `App.tsx` (console branch) |

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
   *close the project and the agent's next call is refused, in the same second*. The MCP
   server gates every tool on a live grant at call time. (Original design: derive
   `tools/list` from grants and push `tools/list_changed`; that still works with
   `APERTURE_STATIC_TOOLS=0`, but **Claude Code ignores the notification** — see
   "Claude Code and tool refresh" below — so the default lists the whole catalog.) The
   onboarding view shows the grants humans hold from the same derivation (`GET /tools`).

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
  tool-name set changes (only with `APERTURE_STATIC_TOOLS=0`). The session is captured
  on the first `list_tools` request.
- Verified with a bare MCP client over stdio (dynamic mode): request → tool appears →
  call ok → approval → second tool appears → close project → both gone → retry refused
  and recorded → chain ok. The `list_changed` notification arrives within ~1s.

### Claude Code and tool refresh (verified 19 Sep, Claude Code 2.1.278)

Claude Code does not re-fetch `tools/list` on `notifications/tools/list_changed`
(anthropics/claude-code#77314, closed "not planned") — interactive or `-p`. A tool
issued mid-session is invisible until the session restarts; `my_access` shows the grant
but the tool can't be called. So the server now defaults to **static listing + call-time
gate**: all catalog tools are listed from the start, a call without a grant is refused
with a message naming who the approval is pending with, and every attempt lands on the
chain (`action_executed` ok/bounced). Verified through a real `claude -p` session:
`gh_read_finance_ledger` refused → `request_access` escalates → refused "pending with
u-finance-owner-1, u-manager-1" → approval → same call returns the repo. Stage script
uses this shape; the "tool vanishes" wording is retired.

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

## Adversarial review (19 Sep, 15:40) — what was found and what changed

Three reviewers ran against their own hub instances: policy decisions, hub API + audit
chain, and the five demo beats + Gemini chat.

Fixed in the hub the same hour:
- approve-replay minted unlimited grants → decided cases take no more votes;
- blast-radius escalation (`resource_id="multiple"`) had no approvers → routed via `APPROVERS`;
- approval after `close_project` still issued a grant → closing a project closes its pending cases;
- approvals granted the requested duration verbatim (3650d) → capped at `MAX_APPROVED_DAYS=30`;
- `POST /audit` accepted any event type/actor (forged `grant_issued` passed verify) → only
  `action_executed`, never reserved actors;
- duplicate resource ids → N grants; repeat asks → duplicate grants and duplicate MCP tools
  → de-duplicated, repeat ask returns the lease already held;
- `requested_duration_days` ≤ 0 accepted → 400;
- Gemini chat: `list_scope` ignored cases awaiting the viewer's vote (Priya was told
  nothing was waiting) → includes `awaiting_my_vote`; chat-driven `request_access` 500'd
  (`run_sync` inside a sync tool) → runs on a fresh thread; Gemini writing the ticket id
  into `project` → pinned to a known project;
- `POST /demo/seed`, `close`, `vote`, `revoke` were open to anyone → `X-Demo-Key` guard
  when `DEMO_KEY` is set.

Still open (say "time-bound", not "continuously reviewed", on stage):
- the engine's `review_active_grants` reaper is never called by the hub; the circuit
  breaker never fires because request history isn't passed; peer percentile is always
  "unavailable" because team sizes aren't passed;
- the vote endpoint trusts `approver_id` in the body (the demo key gates the room, not
  the person);
- REST reads are unscoped (`/audit`, `/escalations`, `/grants?include_revoked=true`
  return everyone's data); the MCP `APERTURE_TOKEN` is only the demo key, not a
  per-person identity;
- `list_scope` has no `person_id`, so a manager asking "what does Alex have?" is answered
  about themselves;
- `backend-api/tests/test_agent_turn.py` (6 tests) has failed since the policy expansion
  — they build requests without a ticket, so the engine now returns `resource_id="all"`.

Confirmed strong: requester spoofing is dead (server-side record wins); gate ordering is
right and every deny has a specific reason; N-of-M voting with sticky veto and snapshot
holds; audit ids/hashes/timestamps are server-assigned; the MCP re-check at call time
works and records the bounce.

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
