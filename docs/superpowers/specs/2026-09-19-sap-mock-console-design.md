# SAP mock console — design

**Status:** implementation spec for a second action platform (SAP Fiori / S/4HANA) beside the existing GCP mock.  
**Does not replace** the Atlas / GCP golden path. GCP remains the main demo; SAP is the second beat so judges can see the same Aperture interface on a Conduct-style client platform.  
**Policy engine** stays the decision core. LLMs never write a Grant.

Related: `docs/console-and-mcp.md`, `docs/superpowers/specs/2026-09-19-enactment-platform-design.md`, `CLAUDE.md` (JIT-Evidence-01).

## Goal

Add a fully built, realistic mock SAP S/4HANA Cloud console. Aperture grants, MCP tools, and Gemini Computer Use work the same way they do on GCP, but the actions are SAP: assign a scoped business role, display one Business Partner, and bounce a customer-file dump.

The Conduct story: client platforms have stacked clearance. An agent cannot run a query and take every customer. It gets one record, for one company code, for one ticket, and the UI plus the policy both enforce that.

## Demo order

1. **Main:** existing GCP Atlas path (bucket auto-grant, finance dataset escalate, computer use on `:8765`).
2. **Second beat:** SAP ask for display on Northwind Trading `1710001`, then an export/directory attempt that is denied and bounced.

Default Atlas asks in `generative-ui/src/aperture/Menu.tsx` stay unchanged. A second control (`SAP_ASK`) fires the SAP request. Do not overwrite Alex’s Atlas ask text.

## Architecture

Two action platforms, one hub:

```
NL / agent / presenter ask
        → parse → policy-engine → Grant | Deny | Escalate
                                      │
                 ┌────────────────────┼────────────────────┐
                 ▼                    ▼                    ▼
           GCP console          SAP Fiori            MCP tools
           :8765                :8766                scoped only
           (unchanged)          (new)                (no dump tool)
```

| Piece | Path | Role |
|---|---|---|
| Mock SAP UI | `agent-runtime/mock_sap/` | Static Fiori console (HTML/CSS/JS), hash routes, hydrates from the hub |
| SAP server | `agent-runtime/mock_sap/server.py` | Same pattern as `mock_console/server.py`, default `127.0.0.1:8766` |
| Seed | `usecase-demo/seed_data.py` | Five new resources; GCP resources stay |
| Types | `shared/schemas.py` | Additive `ResourceType` values only |
| State | `GET /sap/state` | SAP bindings only |
| Routing | `backend-api` `_enqueue_execute` | `sap-*` → `SAP_CONSOLE_URL`, else `CONSOLE_URL` |
| Tools | `agent-runtime/mcp_server.py` | Display tools only |
| Computer use | `agent-runtime/computer_use.py` | SAP verbs + Playwright fallbacks |

GCP `GET /console/state`, `REAL_GCP`, and `sql-prod-primary` never-MCP rules do not change.

## Stacked clearance

A SAP grant is never “access SAP.” It is a role plus restrictions:

| Layer | Display grant | Dump / HR |
|---|---|---|
| Role | `SAP_SD_CUST_DISPLAY` | `SAP_SD_CUST_EXPORT` / payroll role |
| Company code | `1000` London | Frankfurt `2000` is out |
| Customer | Business Partner `1710001` only | All customers |
| Activity | `03` Display | `16` Export |
| Ticket | required | required; still denied |

The Authorization strip on every Fiori page shows the live grant (role, company, customer, valid-to) or “no business role assigned.”

## Seeded company

Fake, demo-safe only. No real customer data.

- System: **SAP S/4HANA Cloud**
- Client: **Helios Manufacturing**
- Company code **1000** London (in scope). **2000** Frankfurt exists in chrome and is always unauthorized for this demo.
- Sales organization `1000`.

Business Partners (Customer Master):

| BP | Name | In display grant? |
|---|---|---|
| `1710001` | Northwind Trading | yes |
| `1710002` | Contoso Retail | no — redacted |
| `1710044` | Litware GmbH | no — redacted |
| `1710108` | Adventure Works | no — redacted |
| `1710200` | Fabrikam Exports | no — redacted |

Billing document `90001234` and sales order `4500008123` belong to `1710001`. Other documents exist in lists but stay redacted without a matching grant.

## Resources

Additive `ResourceType` values:

- `SAP_BUSINESS_PARTNER` = `sap_business_partner`
- `SAP_BILLING_DOCUMENT` = `sap_billing_document`
- `SAP_SALES_ORDER` = `sap_sales_order`
- `SAP_CUSTOMER_DIRECTORY` = `sap_customer_directory`
- `SAP_HR_PAYROLL` = `sap_hr_payroll`

Seed rows (ids are stable; do not rename):

| id | name | type | team | tier | capability | metadata |
|---|---|---|---|---|---|---|
| `sap-bp-display` | Customer Master · Northwind 1710001 | `sap_business_partner` | finance | restricted | `read` | company `1000`, customer `1710001`, role `SAP_SD_CUST_DISPLAY`, activity `03` |
| `sap-billing-display` | Billing · Northwind 90001234 | `sap_billing_document` | finance | restricted | `read` | same company + customer, role `SAP_SD_BILL_DISPLAY` |
| `sap-sales-order-display` | Sales Order · 4500008123 | `sap_sales_order` | data-platform | internal | `read` | same company + customer, role `SAP_SD_SO_DISPLAY` |
| `sap-customer-directory` | Customer Directory / Export | `sap_customer_directory` | finance | critical | `export` | company `1000`, role `SAP_SD_CUST_EXPORT`, activity `16` |
| `sap-hr-payroll` | Employee Payroll | `sap_hr_payroll` | finance | critical | `admin` | locked tile |

Approvers: finance-owned SAP resources → Jordan + Priya (`u-finance-owner-1`, `u-manager-1`). Sales order → Priya only.

Expected policy (Alex, ticket present, data-platform):

| Resource | Decision | Why |
|---|---|---|
| `sap-sales-order-display` | auto-grant | internal, same team, read |
| `sap-bp-display` | escalate | restricted, cross-team to finance |
| `sap-billing-display` | escalate | restricted, cross-team to finance |
| `sap-customer-directory` | auto-deny | `_sap_decision` (dump) |
| `sap-hr-payroll` | auto-deny | `_sap_decision` (payroll) |

GCP decisions stay exactly as they are today (bucket auto-grant, finance dataset escalate, SQL escalate / never-MCP).

## Policy addition (narrow)

Add `_sap_decision` and call it from the existing `_surface_decision` hook (same pattern as PowerBI / GitHub).

- `SAP_CUSTOMER_DIRECTORY` or `SAP_HR_PAYROLL` → `AUTO_DENY` with a human-readable reason, e.g. “Auto-Denied: customer-directory export is not grantable; scope a single Business Partner (Conduct-SAP-01).”
- Other SAP types return `None` and fall through to the existing tier / cross-team rules.

Do not change `_evaluate_level_*`, `DEFAULT_POLICY`, or any GCP / GitHub / PowerBI branch. Do not invent decisions in `backend-api`.

`sql-prod-primary` remains never-MCP and is never CU-enqueued. The two SAP auto-deny ids are also never in `TOOL_SPECS` and never CU-enqueued, even if a grant were forced in tests.

## Parser and asks

Known resource ids come from the seed (GCP + SAP). Parser prompt lists visible names: `Northwind`, `1710001`, `Customer Master`, `billing`, `sales order`, `customer directory`, `export customers`, `payroll`.

| Utterance | Constrained ids |
|---|---|
| “display Northwind Trading 1710001 in Customer Master for INC-8841” | `sap-bp-display` |
| “need the Northwind billing doc and sales order” | `sap-billing-display`, `sap-sales-order-display` |
| “export all customers” / “full customer directory” | `sap-customer-directory` |
| existing Atlas text | existing GCP ids only |

`SAP_ASK` (Alex, Users screen / presenter):

- `resource_ids`: `["sap-bp-display"]`
- `days`: 3
- `text`: “I need display on Northwind Trading customer 1710001 in SAP Customer Master to answer INC-8841. I do not need the full customer file.”
- `context.active_jira_ticket`: `INC-8841`

GCP asks keep `ATLAS-142`. Hub JIT-Evidence-01 still attaches `ATLAS-142` only when a request has no ticket; clients that send `INC-8841` keep it.

## MCP tools

`TOOL_SPECS` additions:

| resource_id | tool name | When |
|---|---|---|
| `sap-bp-display` | `sap_display_bp_1710001` | active grant |
| `sap-billing-display` | `sap_display_billing_northwind` | active grant |
| `sap-sales-order-display` | `sap_display_sales_order_northwind` | active grant |

No specs for `sap-customer-directory` or `sap-hr-payroll`. `tools_for_grants` stays the only derivation of the agent’s tool list.

A call without an active grant writes `ACTION_EXECUTED` with `payload.status = "bounced"`, `grant_id: null`, and `tool` set. Same recorder convention as GCP.

## Mock SAP UI

`agent-runtime/mock_sap/index.html` (plus CSS/JS in that folder if split). Visual language: SAP Fiori Horizon / Quartz Light (blue `#0070F2`, SAP hex logo, 2rem tile grid, object pages). Must read as a client system, not Google Cloud.

**Shell (every page):** product name `SAP S/4HANA Cloud`, client `Helios Manufacturing`, company-code chip `1000 London`, search, notifications, user chip, **Authorization** strip bound to `/sap/state`.

**Hash routes:**

| Hash | App |
|---|---|
| `#launchpad` | tile home (default) |
| `#users` | Maintain Business Users (grant/revoke enactment) |
| `#bp` / `#bp/1710001` | Manage Customer Master |
| `#billing` / `#billing/90001234` | Manage Billing Documents |
| `#sales` / `#sales/4500008123` | Manage Sales Orders |
| `#export` | Export Customer List (always unauthorized in this demo) |
| `#payroll` | Employee Payroll (locked; no navigation) |

**Launchpad tiles:** Customer Master, Billing Documents, Sales Orders, Maintain Business Users (working). Export Customer List (restricted badge, clickable so beat B can fire). Employee Payroll (locked, not clickable).

**Maintain Business Users:** principal, role, company code, customer restriction, valid-to, Save. Keep `#active-grants` list items with `data-resource` + `data-principal` so `verify_active` can be reused or mirrored. Revoke removes the row after confirm.

**Customer Master:** search by BP number or name. With a `sap-bp-display` binding, `1710001` opens a full object page (address, company code, sales area, payment terms). Other BPs render as `••••` / restricted. Opening `1710002` or `1710044` shows `#sap-auth-error` citing `B_BUPA_GRP` and company `1000`.

**Billing / sales orders:** lists filtered to the granted customer when that grant is bound; otherwise redacted. Document pages have header + line items (seeded fake rows).

**Export:** clicking Export or opening `#export` always shows `#sap-auth-error`: “Authorization missing: activity 16 Export. Your grant is display on 1710001 / company 1000.” Do not render a downloadable list.

**Hydration:** `?backend=` or `window.SAP_BACKEND` → `GET {backend}/sap/state`. Apply bindings to `#active-grants`, the Authorization strip, and un-redact only the granted customer. If fetch fails, keep in-page empty state (no role assigned).

## `GET /sap/state`

Returns only SAP resources and bindings from **active** grants whose `resource_id` starts with `sap-`:

```json
{
  "resources": ["…Resource objects…"],
  "bindings": [
    {
      "resource_id": "sap-bp-display",
      "principal": "u-newhire-1",
      "role": "SAP_SD_CUST_DISPLAY",
      "company_code": "1000",
      "customer_id": "1710001",
      "activity": "03",
      "expires_at": "…",
      "grant_id": "…"
    }
  ]
}
```

Role strings come from resource metadata (fallback: `_console_role`). Do not put GCP bindings in this payload. Filter `GET /console/state` bindings to **non-`sap-*`** ids so the GCP console does not grow SAP rows (today it returns every active grant; this spec narrows that).

## Computer use

`execute_grant` (and revoke) chooses the console URL:

- `resource_id` starts with `sap-` → `SAP_CONSOLE_URL` or `http://127.0.0.1:8766/`
- else → `CONSOLE_URL` or `http://127.0.0.1:8765/`

Host allowlist includes both. Never enqueue CU for `sap-customer-directory`, `sap-hr-payroll`, or `sql-prod-primary`.

Closed SAP verb catalog. Each verb has a typed goal, a Playwright fallback, and a DOM verify. Gemini never decides access.

1. **Grant role** — launchpad → Maintain Business Users → principal + `SAP_SD_CUST_DISPLAY` + company `1000` + customer `1710001` + valid-to → Save. Verify `#active-grants` row.
2. **Revoke role** — Remove on that principal → confirm. Verify row gone.
3. **Display BP** — Customer Master → search `1710001` → open. Verify `[data-bp="1710001"]` visible and not redacted.
4. **Display billing** (optional, only if that grant exists) — open `90001234`.
5. **Attempt export** — click Export Customer List. Verify `#sap-auth-error` visible. Audit `ACTION_EXECUTED` with `status: "bounced"`, `action: "export"`, `grant_id: null`.

`grant_goal` for SAP names the Fiori app and the role/restrictions, not the GCP Permissions tab.

## Aperture UI

Matrix, leases, approvals, recorder pick up new rows from `GET /resources` automatically.

Allowed generative-ui edits (narrow):

- `Menu.tsx`: add `SAP_ASK` and `SAP_EXPORT` presenter controls. Do not change Atlas `ASKS`.
- `Summary.tsx` (and `api.ts` label helper if needed): resource guides for the five SAP ids.
- `User.tsx` name matching should recognize “northwind”, “1710001”, “customer master” so a typed ask still maps.

No new Aperture screen. Deny / Approve stay static chrome.

## Data flow

**Beat A (after GCP):** `SAP_ASK` or parsed NL → `POST /requests` with ticket `INC-8841` → engine escalates `sap-bp-display` → approve → `_issue_grant` → `_enqueue_execute` to `:8766` → CU assigns the Fiori role → SAP hydrates from `/sap/state` → MCP lists `sap_display_bp_1710001` → CU may open Customer Master and show only `1710001`.

**Beat B (same session):** `SAP_EXPORT` presenter control (or typed “export all customers”) posts a request for `sap-customer-directory` → engine auto-denies → no grant, no tool, no CU enqueue for that id. Then `_enqueue_execute` is **not** used for the dump. A separate `action=export` computer-use run (presenter or test helper) walks verb 5 against the already-open SAP console: click Export Customer List, verify `#sap-auth-error`, write bounced `ACTION_EXECUTED` with `grant_id: null`. Payroll tile stays locked.

A display grant must not un-redact other customers in the UI or in MCP tool results.

## Tests

Follow existing pytest / Playwright-without-Gemini style.

- Seed: five SAP resources present; all current GCP resources still present.
- Parser: Northwind / 1710001 / Customer Master → `sap-bp-display`; “export all customers” → `sap-customer-directory`; Atlas text still maps only to GCP ids.
- Policy: sales order auto-grants for Alex; BP and billing escalate; directory and payroll auto-deny; bucket + finance dataset decisions unchanged.
- MCP: display tools only while the matching grant is active; no export/payroll tools even if a grant object is forced.
- `GET /sap/state`: SAP bindings include role, company, customer, expiry; no GCP rows.
- `GET /console/state`: still GCP-only bindings.
- Mock SAP: page contains launchpad tiles, `#active-grants`, `#sap-auth-error` hook; hydrates from `/sap/state`; export click reveals the error node.
- Computer use Playwright helpers (no Gemini): grant verify, display-BP verify, export-bounce verify.
- Aperture: `SAP_ASK` exists; Atlas `ASKS` strings unchanged.

## Constraints

- LLMs never write a Grant.
- GCP golden path, mock console, and Atlas asks stay.
- `REAL_GCP` stays grant/revoke IAM on the two demo GCP resources only. No real SAP.
- `mcp` pin stays `<2`.
- `ACTION_EXECUTED` convention stays; additive payload keys only (`action`, existing `status` / `tool`).
- JIT-Evidence-01 stays. SAP demo ticket is `INC-8841`; default fallback remains `ATLAS-142`.
- Do not commit `env.local`, `.env`, keys, or recordings.
- Do not add a real SAP system, RFC, or OData gateway.
- Seed data is fictional (Northwind / Contoso / Litware / Fabrikam).
- `env.example` documents `SAP_CONSOLE_URL` (default `http://127.0.0.1:8766/`).
