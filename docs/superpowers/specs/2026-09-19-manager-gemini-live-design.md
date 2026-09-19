# Manager Gemini Live — design

**Status:** implementation spec for the Aperture Live bubble: conversational Gemini (Live audio + text), actor/focus identity, sponsored requests, and request-specific Computer Use on the GCP and SAP mocks.  
**Does not replace** the five-beat spine, MCP tool list, or the rule that LLMs never write a `Grant`.  
**Does not replace** `2026-09-19-generative-console-design.md` (north-star canvas) or `2026-09-19-sap-mock-console-design.md` (Fiori console). This spec docks onto the existing bubble (`Live.tsx`) and hub (`POST /agent/turn`).

Related: `docs/console-and-mcp.md`, `docs/superpowers/specs/2026-09-19-enactment-platform-design.md`, `CLAUDE.md` (JIT-Evidence-01).

## Goal

Priya Nair (manager view) talks to one Gemini that knows who she is, who she is looking at, and which page she is on. She can type or speak. The thread is shared. She can sponsor access for someone else (confirm → policy). She can ask Gemini to look something up on GCP or SAP; Computer Use drives that console using the **focused person’s** active grant, and Enact shows the turns.

The model is conversational — short, precise, one clarifying question when the person or resource is ambiguous — not a policy cop and not a silent granter.

## Thesis

Live is a colleague sitting on the console, not a second product. The same engine, grants, and Computer Use loop already used after a grant are what the bubble may start. Policy is not bypassed because the speaker is a manager.

## Non-negotiables

- LLMs never write a `Grant`. Sponsor is `request_access_for` → confirm card → parse → `_evaluate_request`.
- Chat and Live **cannot vote**. Approve / Deny stay static chrome in `Approvals.tsx`.
- Chat and Live **cannot** enqueue Computer Use `grant` or `revoke`. Those stay on the policy path after a real grant or revoke.
- Computer Use `browse` / `query` / `inspect` runs only against an **active, unexpired grant** whose `requester_id` is the **focus** person (or a person unambiguously named in the current turn).
- `sql-prod-primary` and `sap-hr-payroll` stay in `NEVER_ENACT_IDS` (no CU at all). `sap-customer-directory` is never granted; the only allowed CU on it is `action=export` to show the bounce (`#sap-auth-error`, `grant_id` null). No grant/revoke/browse CU on that id.
- Every request still needs business context (JIT-Evidence-01). GCP / Atlas default ticket `ATLAS-142`. SAP asks that already carry `INC-8841` keep it. The hub must not overwrite a ticket the client sent.
- `REAL_GCP` stays grant/revoke IAM only. Chat does not call `google-cloud-*`.
- Deny / Approve are never generated. Presenter DemoBar stays presenter chrome.

## Architecture

```
Browser Live bubble
  text  ──► POST /agent/turn { viewer_id, focus_id, page, message, conversation_id, confirm? }
  audio ──► Gemini Live session (same conversation_id, same tools)
                │
                ▼
        console agent (Pydantic AI + Gemini)
          tools: list_scope, explain_decision,
                 request_access, request_access_for, enact
                │
                ├─ request_*  → parse → confirm → policy-engine → Grant | Deny | Escalate
                └─ enact      → active grant of focus person
                                 → _enqueue_execute(grant, action, ask)
                                 → computer_use on :8765 (GCP) or :8766 (SAP)
                                 → ACTION_EXECUTED frames → Enact + bubble
```

One agent. Two mouths (Live audio, text). One `conversation_id`. Tools stay server-side; the browser never holds `GEMINI_API_KEY`.

## Conversation

There is one Gemini, one `conversation_id`, one transcript stored on `CONVERSATIONS[id].messages`.

- **Live** is the demo path: Gemini Live native audio (AI Studio key, not Vertex). Conversational turn-taking. It may ask one short follow-up before a tool. Model pin at wire time; default the current Live-capable Flash (`gemini-2.5-flash-native-audio` unless superseded in `gemini_models.py`).
- **Text** is the same bubble for typed asks. Same tools, same system prompt, same history.
- Switching mic ↔ keyboard does not reset the thread.
- Every model turn receives typed context (below) plus the last messages (cap: 20 turns). Requester free text in history is a claim, never fed into `summarize_decision`.
- Tool calls render as rows (`used query`, `used request_access_for`). Confirm cards stay shell chrome.
- If Live audio cannot start: mic falls back to browser Web Speech, then to text. Caption + transcript always remain. The bubble never depends on Live to render.
- Host for Live: backend (or existing Modal execute host) proxies the session so tools and parse stay next to MCP. Do not embed an unconstrained public Live demo.

Tone: intellectual colleague. Short sentences. Name the person and the platform. Do not dump policy ids unless asked why.

## Identity: actor vs focus

Today one dropdown sets `me` and is passed as `viewer_id`, so picking Jordan makes Gemini speak *as* Jordan. Split them.

| Field | Meaning | Manager default | User role |
|---|---|---|---|
| **Actor** | Signed-in human. Gemini addresses them. Sponsor and audit `actor` use this id. | Priya Nair (`u-manager-1`) | The selected requester |
| **Focus** | Card, chip, or Timeline filter. Computer Use uses this person’s grant. | Everyone (`all`) | Same as actor (no split) |

**Chrome**

- Keep User | Manager.
- **Signed in as** lists only people who can hold that role (manager/owner/lead/head for Manager; requesters for User). This is the actor.
- Person cards and Timeline chips set **focus** only.
- Bubble subtitle: `as Priya Nair · looking at Jordan Lee` or `looking at everyone`.

**Payload on every `/agent/turn` and Live setup**

`POST /agent/turn` keeps `viewer_id` as the **actor** (existing clients keep working). Add optional `focus_id` (`null` / `"all"` / omitted = everyone) and `page` (`overview` | `timeline` | `onboard` | `access`). `role` is derived server-side from the actor (`roleOf` rules: manager/owner/lead/head → manager), not trusted from the client.

```python
class ConsoleContext(BaseModel):
    actor_id: str          # = body.viewer_id
    focus_id: str | None   # None or "all" = everyone
    page: Literal["overview", "timeline", "onboard", "access"]
    role: Literal["user", "manager"]
```

Server looks up actor and focus in `KNOWN_REQUESTERS`. Ignore client-supplied name/team/role. Unknown `viewer_id` → HTTP 400 `unknown requester`.

**Conversation lifetime**

- New `conversation_id` when **actor** or `role` changes.
- Same thread when only focus or `page` changes. The model is told the new page/focus; it does not forget the chat.

**Computer Use subject**

- Focus is a person → that person’s grant.
- Focus is everyone and the utterance names one known person → that person.
- Otherwise Gemini asks once who to look at. It does not pick a grant at random.

## Tools

Closed set. Illegal verbs stay refused: `grant`, `vote`, `close_project`, `patch_policy`, and enact `grant`/`revoke`.

| Tool | Input | Server does |
|---|---|---|
| `list_scope` | — | Actor’s active grants; **cases waiting on the actor** (`required_approver_ids`); focus person’s active grants and pending requests; open escalations visible in manager view. No invented counts. |
| `explain_decision` | `request_id?`, `resource_id?` | Typed `POLICY_EVALUATED` / escalation reason. Prefer `summarize_decision` only with a `PolicyDecision` in hand. Never pass requester `raw_text` into the summarizer. |
| `request_access` | `raw_text` | Parse as **actor**. First call: `needs_confirmation` preview. Confirm evaluates as actor. |
| `request_access_for` | `beneficiary_id`, `raw_text` | Resolve beneficiary in `KNOWN_REQUESTERS` (id or unique display name). Parse as **beneficiary**. Preview includes beneficiary, resources, duration, project, `sponsored_by=actor`. Confirm: `AccessRequest.requester = beneficiary`, `metadata.sponsored_by = actor_id`. Then `_evaluate_request`. |
| `enact` | `action`, `raw_text`, `resource_id?` | Resolve resource from parse of `raw_text` if omitted. Load **active** grant for `(focus_or_named_person, resource_id)`. Enqueue `_enqueue_execute(grant, action, ask=raw_text)`. If no grant: do not enqueue; return `{status: "no_grant"}` so Gemini can offer to sponsor. |

`request_access` remains for “I need the bucket” when the actor is asking for themselves (Alex, or Priya for her own lease).

Confirm without pending → HTTP 400 `nothing to confirm`. Confirm must belong to this actor.

## Platforms and enact catalog

`enact.action` is closed: `browse` | `query` | `inspect` | `export`.

| Platform | Resource | Action | CU does | No grant |
|---|---|---|---|---|
| GCP `:8765` | `bucket-analytics-raw` | `browse` | Storage → Objects → object named in `ask` (default `events/2026-09-18.parquet`). Verify `#object-preview`. | Offer sponsor |
| GCP | `bq-project-x-finance` | `query` | BigQuery → dataset → Query → read-only SELECT matching `ask`. Verify `#query-results`. | Offer sponsor |
| GCP | `sql-prod-primary` | — | Refuse. Never enqueue. | Explain critical / never-MCP |
| GCP | `repo-*` | — | Out of CU for this spec (MCP already has tools). Gemini explains; does not invent a GitHub console. | — |
| SAP `:8766` | `sap-bp-display` | `inspect` | Customer Master → BP in `ask` if covered by the grant (default `1710001`). Verify `[data-bp="1710001"]` visible, not redacted. | Offer sponsor |
| SAP | `sap-billing-display` | `inspect` | Billing `90001234`. | Offer sponsor |
| SAP | `sap-sales-order-display` | `inspect` | Sales order `4500008123`. | Offer sponsor |
| SAP | `sap-customer-directory` | `export` | Open Export Customer List. Verify `#sap-auth-error` visible. Audit bounce, `grant_id` null. | Do not sponsor; hard deny |
| SAP | `sap-hr-payroll` | — | Refuse. Locked tile. Never enqueue. | Same |

Console URL unchanged: `sap-*` → `SAP_CONSOLE_URL` or `http://127.0.0.1:8766/`, else `CONSOLE_URL` or `http://127.0.0.1:8765/`. Host allowlist includes both.

Parser must map platform language to seed ids (analytics-raw / GCS, project-x-finance / BigQuery, Northwind / `1710001` / Customer Master, billing, sales order, export customers, payroll). Do not invent resource ids.

## Computer Use must follow the ask

Today `enact_goal(grant, action)` is canned (always the parquet, always a generic SELECT) and `run_computer_use_loop` never sees the human sentence. Browse/query “succeed” via `verify_active` (IAM row), which is the wrong check.

Required changes in `agent-runtime/computer_use.py` (and enqueue):

1. **`enact_goal(grant, action, ask: str | None)`** — existing nav + selectors, plus the current ask. The vision model is steered to that object, query, or BP.
2. **Closed playground** — stay on the mock host, only that `resource_id`, read-only for chat-started actions. Do not open Permissions → Grant from `browse`/`query`/`inspect`.
3. **Verify the outcome**
   - `browse` → `#object-preview` matches the named object
   - `query` → `#query-results` for that dataset
   - SAP `inspect` → the granted object is visible and not redacted
   - `export` → `#sap-auth-error` has class `visible`
   - `grant` / `revoke` → existing `verify_active` / `verify_inactive` (unchanged, not callable from chat)
4. **Playwright fallbacks** for the demo paths (parquet, finance SELECT, Northwind BP, billing doc, sales order, export bounce) so a missed click still completes.
5. **`_enqueue_execute(grant, action, ask=None)`** — pass `ask` into `execute_grant` / the Modal payload. Chat and the post-grant path share this function.
6. **One run at a time** per grant. A second `enact` on the same grant while `phase=started` is unanswered waits or returns `{status: "running"}`. Gemini says it is already looking.

Gemini never decides access. A bounced export is evidence, not a grant.

## Policy routes (platform-specific, additive)

Do not replace `DEFAULT_POLICY` tiers. Do not invent decisions in `backend-api`. Extend `_surface_decision` only.

### GCP — `_gcp_decision` (new)

Called for GCS / BigQuery / Cloud SQL (and not for SAP types).

| Resource | Typical decision (Alex, ticket present) | Route |
|---|---|---|
| `bucket-analytics-raw` | auto-grant (internal, same team) | — |
| `bq-project-x-finance` | escalate | Jordan + Priya (`owner` + `manager`) |
| `sql-prod-primary` | escalate | Jordan + Priya; never enact |
| `repo-atlas-ingestion` | auto-grant (internal, same team) | — |
| `repo-finance-ledger` | escalate | Jordan + Priya |

Metadata on every GCP decision: `platform: "gcp"`. Reasons may name the GCP product. Existing golden path must stay: bucket auto-grant, finance escalate, SQL escalate.

### SAP — expand `_sap_decision`

Keep Conduct-SAP-01.

| Resource | Decision | Route / note |
|---|---|---|
| `sap-sales-order-display` | auto-grant if internal + same team | Priya only if escalated |
| `sap-bp-display` | escalate if restricted / cross-team | Jordan + Priya; reason names Fiori role, company `1000`, customer `1710001` |
| `sap-billing-display` | same | same |
| `sap-customer-directory` | auto-deny | Conduct-SAP-01 |
| `sap-hr-payroll` | auto-deny | Conduct-SAP-01 |
| Company `2000` / Frankfurt, or a BP outside the grant | deny or CU bounce | Not a new Grant |

Metadata: `platform: "sap"`, plus role, company, customer, activity from resource metadata.

Tickets: SAP clients sending `INC-8841` keep it. GCP / Atlas keep `ATLAS-142`.

### Sponsorship routing

Evaluate as the **beneficiary**. If `metadata.sponsored_by` is in the would-be `required_approver_ids`, **omit that id** from the case (the sponsor does not vote themselves). The other side still votes — Jordan still decides finance-owned GCP and SAP. Export and payroll stay deny even if Priya sponsors.

Audit: `REQUEST_RECEIVED` `actor` = sponsor (`Priya`), payload includes `beneficiary_id` and `sponsored_by`. `Grant.requester_id` is the beneficiary.

`GET /policy` and the manager Policy panel show **two route lists** (GCP / SAP), not only tier × days × approvals. `explain_decision` and `list_scope` use the same typed reasons.

Do not edit `tests/test_engine.py` golden cases except to add new GCP/SAP surface tests. Existing Atlas assertions stay green.

## Watch

- **Enact on Timeline** is the stage. Chat-started runs emit the same `ACTION_EXECUTED` convention (`phase`, `screenshot_url`, `action`, `mode`, `watch_url` optional).
- **Bubble** shows a tool row and a latest-still thumbnail. Gemini narrates. Tap the thumbnail to focus Enact.
- **Overview has no Enact.** On first `enact`, the shell switches to Timeline, keeps `conversation_id`, sets **focus** to the grant holder. Actor unchanged.
- Bounce is a red tool row. No fake success.
- Live may speak a short status line while frames arrive. It must not start a second CU on that grant until `completed`.

## Manager surface (this spec)

Keep people cards, approvals, and the policy table. Change:

1. Actor vs focus chrome (above).
2. Policy table split GCP / SAP routes.
3. `list_scope` for a manager includes the approval queue (cases where `actor` is a required approver). “Who is waiting on me?” must be answerable from tools.
4. Live bubble on every screen, as today.

Out of scope: generated Approve/Deny, chat-driven grant/revoke CU, replacing DemoBar, rewriting MCP `tools_for_grants`.

## Error handling

| Case | Behaviour |
|---|---|
| Live audio unavailable | Fallback Web Speech, then text. Mic stays visible. |
| Gemini text / tools unavailable | Bubble shows a short offline line. No silent tool success. |
| Unknown actor | HTTP 400 |
| `enact` with no matching grant | Tool result `no_grant`; Gemini offers sponsor if the resource is grantable |
| `enact` SQL / payroll | Refuse in the tool; no enqueue |
| `export` | Enqueue bounce only; never a Grant |
| Confirm with no pending | HTTP 400 |
| CU sandbox / key missing | `ACTION_EXECUTED` `success: false`, `reason: gemini_unavailable` or `sandbox_error`. Gemini says it could not open the console. |

## Testing

Offline by default (injected runner / PARSE_IMPL / EXECUTE_ENQUEUE_IMPL). Live Gemini and Live audio are optional smokes, never required in pytest.

Minimum coverage:

- System prompt still refuses `grant`, `vote`, `close_project`, `patch_policy`.
- `list_scope` as Priya returns cases waiting on her, not only cases she requested.
- `request_access_for` confirm evaluates as Jordan; `Grant.requester_id` is Jordan; audit actor is Priya; Priya omitted from required approvers if she would have been one.
- `request_access_for` on `sap-customer-directory` is denied; no grant; no CU grant.
- `enact` without a focus-person grant does not call `_enqueue_execute`.
- `enact` with Jordan’s finance grant calls enqueue with `action=query` and the raw ask.
- `enact_goal(..., ask=)` includes the ask; browse/query verify is not `verify_active`.
- Actor change mints a new conversation; focus change does not.
- Existing `test_agent_turn.py` confirm path and Atlas golden path stay green.

## File map (implementation)

- `agent-runtime/console_agent.py` — context in prompt, new tools, history
- `agent-runtime/computer_use.py` — `ask` on goals, verify by action, Playwright fallbacks
- `agent-runtime/gemini_models.py` — pin Live model id
- `backend-api/main.py` — `ConsoleContext`, conversation messages, `_console_request_access_for`, `_console_enact`, `_enqueue_execute(..., ask)`, omit sponsor from `required_approver_ids` when opening a case
- `policy-engine/engine.py` — `_gcp_decision`; richer `_sap_decision` (existing Atlas tests stay green). Manager Policy UI groups `GET /resources` + `APPROVERS` into GCP vs SAP; `GET /policy` stays the tier table plus those grouped routes
- `generative-ui/src/aperture/App.tsx`, `Menu.tsx`, `Live.tsx`, `Manager.tsx` — actor/focus, context payload, Enact navigation, dual policy table
- Tests beside each of the above

Do not rewrite `mcp_serve.py` / `tools_for_grants`. Do not commit `env.local`, keys, or recordings.

## Demo beats this unlocks

1. Manager Overview as Priya. Live: “Who is waiting on me?” → queue from `list_scope` (Alex’s finance case).
2. Focus Jordan. “Grant Jordan read on the analytics bucket for Atlas.” → confirm card as Jordan → policy (cross-team Storage) → no silent IAM.
3. Focus Jordan (he holds finance). “What’s in the finance dataset for Atlas invoice lines?” → CU query on `:8765` → Enact.
4. “Show me Northwind in Customer Master.” → CU inspect on `:8766` if he has `sap-bp-display`; else offer to sponsor.
5. “Export all customers.” → deny / export bounce. Gemini does not claim it dumped the file.

## Open questions (resolved in this spec)

- Bypass policy? **No.**
- Manager grant meaning? **Sponsor.**
- CU subject? **Focus person.**
- Live vs text? **Both, one memory; Live is conversational.**
- Platforms? **GCP + SAP catalogs above.**
