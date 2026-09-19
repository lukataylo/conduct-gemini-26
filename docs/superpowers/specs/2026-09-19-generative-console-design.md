# Generative Console — finished-product design

**Status:** north-star spec for track 1 + the track 2 compose / Live agent.  
**Does not replace tonight's five-beat spine.** The MCP tool list is still the agent's access surface. This document is what the human-facing product is when it is built.

Related: `docs/ui-surfaces.html` (surfaces 2, 4), `generative-ui/README.md`, `shared/schemas.py`.

## Goal

Every viewer gets a **console generated for them** — not a shared admin portal with filters. Gemini composes a workspace from that viewer's role, active grants, open cases, and recent audit. The workspace always contains four regions:

1. **Analytics** — a scope / lease / activity view of *their* aperture
2. **Quick actions** — task-sized verbs, each with a server-checked `action_id`
3. **Chat** — text talk with the access agent
4. **Gemini Live** — voice talk with the same agent, same tools, same conversation

The model still never grants. It composes layout and talks. The policy engine decides. Approve and Deny stay static chrome.

## Thesis

The coding agent's UI is its tool list. The human's UI is a **personal operating surface** for the same grants: see the aperture, act on it, and talk to an agent that can request, explain, and navigate — but cannot override policy.

Alex's console is an intern's two-grant analytics board plus a Live mic. Priya's is a queue and SLA board plus the same mic. They do not share a layout.

## Non-negotiables

- LLMs never write a `Grant`. Chat and Live call `request_access`; that is parse → `POST /requests` → engine.
- Live and chat **cannot vote**. Approve / Deny are not tools and not catalog entries. They sit in a fixed shell slot when `role=approver`.
- Gemini never invents analytics numbers. It only **picks widgets**. Series come from `/grants`, `/escalations`, `/audit` filtered to the viewer.
- Off-catalog component names render `UnknownComponent`. After compose, the server drops any panel whose `grant_id` / `escalation_id` / `action_id` is not in the viewer's allowed set.
- Full tree replace on every token is forbidden. Diff on `panel.id`. Data-model updates stream over SSE; layout regenerates only on scope change (grant issued, revoked, role switch, Live-requested recomposition).
- Requester free text is a claim. It may appear in chat history and in a labelled quote on an approval card. It never enters `summarize_decision` or analytics titles.

## Shell vs generated canvas

The **shell is static**. Gemini fills regions; it does not invent the frame.

```
┌─ shell (static) ─────────────────────────────────────────────┐
│ Aperture · {viewer.name} · {role}              [Live mic]    │
│ [QuickActionBar — generated items, fixed strip]              │
├──────────────────────────────────┬───────────────────────────┤
│ MAIN (generated)                 │ CONVERSATION (static dock)│
│   Analytics widgets              │   Chat transcript         │
│   Grant / pending / denied cards │   Live captions           │
│   Approver vote chrome (fixed    │   same Conversation id    │
│   bottom of MAIN if approver)    │                           │
└──────────────────────────────────┴───────────────────────────┘
```

- **Live mic** is always in the chrome so Gemini cannot hide voice.
- **Conversation dock** is always on the right (collapsible). Chat and Live share one `conversation_id`.
- **QuickActionBar** is always the second row. Contents are generated; the row is not.
- **Vote chrome** is always the bottom of MAIN for approvers, even if Gemini emits zero pending cards.

## The four regions

### 1. Analytics (generated selection, server data)

Catalog widgets. `compose_console` chooses a subset and order from role and scope size. Data payloads are attached by the server after compose.

| Widget | Component name | Data source | Typical viewer |
|---|---|---|---|
| `ScopeMap` | territory / iris of resources they can currently touch | active grants + resource catalog | requester |
| `LeaseGantt` | bars that end at `expires_at`; pending hatched; project-close is a vertical cut | grants + open cases | requester, auditor |
| `QueueSLA` | pending cases, `sla_due_at`, missing voters | escalations where viewer is required | approver |
| `PeerSignal` | "0 of 6 on data-platform hold `project-x-finance`" | seed / grant history | approver |
| `FlightRecorder` | `ACTION_EXECUTED` nested under the grant that authorised them | `/audit` for viewer | auditor, requester |
| `ChainHealth` | last `/audit/verify` result + chain length | `/audit/verify` | auditor |
| `HoldingsStrip` | compact grant count, soonest expiry, pending count | grants + cases | all (fallback if compose fails) |

If compose fails or returns nothing in MAIN, the server injects `HoldingsStrip` plus existing `GrantCard` / `PendingApprovalCard`. The console never renders an empty main column.

Analytics titles may be rewritten by Gemini from widget type + resource names. Values (`14d`, `2 pending`, verify `ok`) are not.

### 2. Quick actions

Catalog: `QuickActionBar` with `actions: [{ action_id, verb, label, target_id? }]`.

Closed verb set (server enum, not free text):

| Verb | Who | What the server does |
|---|---|---|
| `request_access` | requester | opens the confirmation card with the last parsed `AccessRequest` or starts chat with a prompt |
| `relinquish_grant` | requester | `POST /grants/{id}/revoke` reason=`relinquished` — only their grant |
| `nudge_approver` | requester | audit event + optional Live line; does not grant |
| `explain_decision` | any | asks the agent to speak/write from the typed `PolicyDecision` only |
| `verify_chain` | any | `GET /audit/verify` and patch `ChainHealth` |
| `remind_peer` | approver | audit event toward the other required voter |
| `jump_to_case` | approver | client focuses that `PendingApprovalCard` |
| `export_trail` | auditor | download `/audit?request_id=` |

Illegal verbs (never in the enum, never registered as Live tools): `grant`, `vote`, `close_project` (presenter-only tonight), `patch_policy`.

Every click POSTs `{ action_id }` to `POST /actions/{action_id}`. The server looks up the issued `action_id`, checks verb + viewer + target still allowed, then runs. A generated label cannot change the verb.

### 3. Chat

Text I/O to the **console agent** (track 2, Pydantic AI + Gemini, Logfire). Same agent as Live.

Tools the agent may call (mirrors MCP, plus console navigation):

- `request_access(raw_text)` → parse → `POST /requests` (never a grant)
- `list_scope()` → viewer's active grants and pending cases
- `explain_decision(request_id, resource_id)` → typed decision + `summarize_decision`
- `navigate(panel_id)` → SSE `focus_panel` so the canvas highlights a card or widget
- `compose_refresh()` → rebuild `UISpec` after a scope change the agent just caused

Chat confirmation: when `request_access` is about to POST, the dock shows a confirmation card (resource ids, duration, project). The human taps send. That card is shell, not catalog.

### 4. Gemini Live

Voice I/O to the **same console agent and the same `conversation_id`**.

- API: Gemini Live on the existing AI Studio key (`GEMINI_API_KEY` / `GEMINIAPIKEY`). Not Vertex. Model: the current Live-capable Flash (pin in `agent-runtime` at wire time; default `gemini-2.5-flash-native-audio`).
- Host: Modal function in agent-runtime, so tools and parse stay next to MCP. The browser opens a Live session against that endpoint; it does not embed an unconstrained public Live demo.
- Session is bound to `X-Actor` / viewer bearer. The model receives role, holdings, and open cases as **typed context**, not the requester's raw pitch as instructions.
- Audio out + captions land in the conversation dock. Tool calls appear as chat rows (`agent used request_access`).
- Live may **talk through** a grant change ("the bucket is yours; `gcs_list_objects` is on your agent's list") after the engine has already issued it.
- If Live is unavailable, the mic control stays visible and disabled with "voice offline — use chat". The rest of the console does not depend on Live.

## Per-person compositions (the generated part)

`compose_console(viewer, role, grants, cases, audit_digest) -> UISpec`

`audit_digest` is a server-built summary (counts, soonest expiry, last verify, open SLA). The model does not read the raw trail.

| Viewer | Role | MAIN | Actions | Conversation opener |
|---|---|---|---|---|
| Alex Chen | requester | `ScopeMap` + `LeaseGantt` + GrantCard(s) + PendingApprovalCard | `request_access`, `relinquish_grant`, `nudge_approver` | "You have the analytics bucket. Finance is waiting on Priya and Jordan." |
| Priya Nair | approver | `QueueSLA` + `PeerSignal` + pending cards | `explain_decision`, `remind_peer`, `jump_to_case` | "One Atlas case needs you. Cross-team, restricted." |
| Jordan Lee | approver | finance-owned pending + `PeerSignal` | same as Priya | "Alex wants `project-x-finance`. You are the data owner." |
| Auditor | auditor | `FlightRecorder` + `ChainHealth` + `LeaseGantt` | `verify_chain`, `export_trail` | "14 events on Atlas. Chain ok." |

Same store. Four workspaces. That is the originality of this surface: **your version is specific to you.**

## Composition pipeline

1. Viewer opens `/` with `role` + `X-Actor`.
2. Backend loads grants, cases, `audit_digest` for that viewer.
3. Backend calls track 2 `compose_console` (Modal). Timeout 2s. On failure or invalid spec → deterministic fallback layout for that role (table in "Per-person compositions", minus Gemini labels).
4. Server attaches data payloads, issues `action_id`s, strips illegal panels.
5. Client diffs `panel.id` into MAIN and the action strip.
6. On `grant_issued` / `grant_revoked` / vote: SSE data-model patch first (numbers and cards). Recompose only if the set of grant/case ids changed.
7. Chat / Live `request_access` that results in a new grant follows step 6. Live is allowed to narrate the patch.

`GET /ui-spec/{viewer_id}?role=` remains the read API. `?mode=generated` is the Gemini path; omit or `mode=fallback` for the deterministic layout. Tonight's hub already implements the fallback without `role`; adding `role` is additive.

## Schema additions (additive)

```python
class ViewerRole(str, Enum):
    REQUESTER = "requester"
    APPROVER = "approver"
    AUDITOR = "auditor"


class ConsoleRegion(str, Enum):
    ANALYTICS = "analytics"
    MAIN = "main"          # cards + analytics sit together in MAIN
    ACTIONS = "actions"


class QuickActionVerb(str, Enum):
    REQUEST_ACCESS = "request_access"
    RELINQUISH_GRANT = "relinquish_grant"
    NUDGE_APPROVER = "nudge_approver"
    EXPLAIN_DECISION = "explain_decision"
    VERIFY_CHAIN = "verify_chain"
    REMIND_PEER = "remind_peer"
    JUMP_TO_CASE = "jump_to_case"
    EXPORT_TRAIL = "export_trail"


class QuickAction(BaseModel):
    action_id: str          # server-issued
    verb: QuickActionVerb
    label: str
    target_id: str | None = None


class Conversation(BaseModel):
    id: str
    viewer_id: str
    role: ViewerRole


class UIComponentSpec(BaseModel):
    id: str
    component: str
    region: ConsoleRegion = ConsoleRegion.MAIN
    props: dict = Field(default_factory=dict)


class UISpec(BaseModel):
    viewer_id: str          # rename from requester_id; keep requester_id as alias
    role: ViewerRole = ViewerRole.REQUESTER
    conversation_id: str | None = None
    actions: list[QuickAction] = Field(default_factory=list)
    panels: list[UIComponentSpec]
    generated_at: datetime = Field(default_factory=_utcnow)
    fallback: bool = False  # true when Gemini was skipped
```

Keep `requester_id` as an optional alias on `UISpec` so today's client does not break. Track 1 mirrors the new fields in `generative-ui/src/types.ts`.

New catalog keys (track 1): `ScopeMap`, `LeaseGantt`, `QueueSLA`, `PeerSignal`, `FlightRecorder`, `ChainHealth`, `HoldingsStrip`, `QuickActionBar`, `DeniedPanel`. Existing: `GrantCard`, `PendingApprovalCard`, `AuditTimeline`.

## Runtime placement

| Piece | Owner | Why |
|---|---|---|
| Shell, registry, vote chrome, Live mic, chat dock | track 1 | Human surface |
| `compose_console`, console-agent tools, Gemini Live host | track 2 | All model I/O stays in agent-runtime |
| Grants, actions, SSE, `action_id` minting | track 5 | Only writer |
| Decisions | track 3 | Unchanged |
| Presenter close-project | track 4 | Not a viewer quick action |

Track 2's MCP server and the console agent are two clients of the same grant store. A Live `request_access` and Claude Code `request_access` hit the same parse function.

## Demo, when this is built

Split screen stays. Left: Claude Code (agent aperture). Right: **Alex's generated console** (human aperture).

Beat 2: Alex's `ScopeMap` lights the bucket; `LeaseGantt` draws a 14-day bar; finance is hatched pending. The dock says the sentence in the table above. Optional: tap Live — "what's waiting?" — same sentence spoken.

Beat 3: switch role to Priya. The canvas **re-composes**: queue + SLA, not Alex's iris. Vote chrome appears at the bottom. Live: "why did this escalate?" → `explain_decision` from the typed reason.

Beat 5: close Atlas. Alex's bars and cards leave; Live can say they are gone; Claude Code loses the tools in the same second.

If Live flakes, chat or silence. The visual close does not wait on audio.

## Tonight vs this spec

| Tonight (wins execution) | This spec (the product) |
|---|---|
| Static `UISpec` of GrantCard + PendingApprovalCard | Per-viewer compose into analytics + cards |
| Chat input + confirmation (if track 1 gets to it) | Chat + Gemini Live, one conversation |
| No quick-action strip | Server-issued `action_id` verbs |
| Approver view + vote button | Same vote chrome, plus Priya's generated queue |
| MCP vanish-on-close | MCP vanish + console recomposition + optional Live line |

Do not start Live, `ScopeMap`, or `compose_console` until the five-beat spine has run twice. This spec exists so track 1 does not build a dead-end portal, and so track 2's `compose_ui` / agent tools aim at a real console instead of three cards that look like the fallback.

## Judge answers this spec adds

- "Where is the generative UI?" — "This workspace was composed for Priya. Alex's is a different tree from the same grants. Here is the catalog; here is an off-catalog name failing closed."
- "Can I talk to it?" — "Yes. Live and chat are one agent. Ask it to request access and it still has to go through the engine. Ask it to approve and it cannot."
- "Isn't this a chatbot with charts?" — "The charts are your lease. The actions are re-checked. The left pane is still the coding agent's tools disappearing when the project closes."

## Conflicts with what is already on `main`

Landed immediately after this spec: `28fc00f` (lukataylor-pixel) — *Build the Aperture requester app: lease timeline + flight recorder*. Git-clean on our files. Product-overlap is real. Integrate; do not rewrite.

### What they shipped

- `generative-ui/src/main.tsx` now mounts `aperture/App.tsx`, not the registry `App.tsx`.
- Hardcoded **Alex-only** shell: summary strip, `Timeline` (leases), `Recorder` (audit + tool calls nested under grants), `DemoBar`.
- Polls `/grants?include_revoked=true`, `/escalations`, `/audit`, `/audit/verify` every 1.5s. **Does not consume `UISpec`.**
- `DemoBar` drives the golden path from Alex's screen: Request (hand-built `AccessRequest`) → Approve (casts every required vote) → Call tool (synthesises `ACTION_EXECUTED`) → Close project.
- Backend: `GET /grants?include_revoked=` — default remains active-only.

### How this maps to this spec

| This spec | Their code | Rule |
|---|---|---|
| `LeaseGantt` | `aperture/Timeline.tsx` | Treat Timeline as LeaseGantt v0. Do not add a second Gantt. |
| `FlightRecorder` | `aperture/Recorder.tsx` | Treat Recorder as FlightRecorder v0. |
| `HoldingsStrip` / `ChainHealth` | header summary + `chain ok` | Already on the shell. |
| `ScopeMap`, `QueueSLA`, `PeerSignal` | missing | Add later; do not replace Timeline/Recorder to make room. |
| Chat + Gemini Live | missing | Dock onto **their** shell. Do not resurrect registry `App.tsx` as the demo entry. |
| Quick actions | `DemoBar` | DemoBar is **presenter chrome** (like `/demo`). It is not the product action strip and not an approver. |
| Registry + `compose_ui` catalog | still in repo, unused at boot | Keep for generated mode. Register `LeaseGantt`/`FlightRecorder` as aliases of Timeline/Recorder when compose is wired. |
| `UISpec.viewer_id` rename | unused by their app; still required by `compose_ui` + `/ui-spec` | **Do not rename `requester_id`.** Additive fields only. |
| Approver vote chrome | DemoBar auto-votes as Priya and Jordan | Fine for a four-minute run. Beat 3 for judges still needs a real Priya view; do not delete DemoBar. |

### Landmines

- **`GET /grants` default must stay active + unexpired.** MCP `tools/list` uses it. Never pass `include_revoked=true` from the runtime. Timeline is the only caller of that flag.
- **Do not bypass policy from new console features** the way DemoBar `Approve` does. New chat/Live/quick-action paths go parse → engine. DemoBar stays labelled `demo`.
- **Do not POST synthetic `ACTION_EXECUTED` from the console agent.** DemoBar's "Call tool" is a presenter stub. Real calls come from MCP or computer use.
- **Local track-2 WIP** (`envutil`, `gemini_parser`, `a2ui`, `computer_use`, `gemini_models.py`) does not overlap their files. Rebase/push that separately; do not bundle it with console-spec edits.
- **Docs still disagree:** `agent-runtime/README.md` says MCP is core; `docs/superpowers/plans/2026-09-19-agent-runtime-core.md` says MCP is out of scope. This spec does not resolve that. `compose_ui` vs `compose_console` is the same function grown in place — do not add a second composer.
