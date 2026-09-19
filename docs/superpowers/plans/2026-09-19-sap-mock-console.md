# SAP Mock Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a realistic mock SAP Fiori / S/4HANA console as a second action platform so the demo can show scoped customer-master access and a bounced dump after the GCP Atlas path.

**Architecture:** Additive `ResourceType`s and five seed resources feed the existing request → policy → grant path. `_sap_decision` auto-denies directory and payroll. A new static console on `:8766` hydrates from `GET /sap/state`. Computer use routes `sap-*` grants to that URL. MCP exposes only the three display tools. Atlas / GCP behavior stays.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, pytest, Playwright, existing mock-console HTML pattern, React Aperture console.

## Global Constraints

- LLMs never write a Grant.
- GCP golden path, mock console, and Atlas `ASKS` strings stay unchanged.
- `REAL_GCP` stays grant/revoke IAM on the two demo GCP resources only. No real SAP.
- `mcp` pin stays `<2`.
- `ACTION_EXECUTED` convention stays; additive payload keys only (`action`, existing `status` / `tool`).
- JIT-Evidence-01 stays. SAP demo ticket is `INC-8841`; default fallback remains `ATLAS-142`.
- Do not commit `env.local`, `.env`, keys, or recordings.
- Do not add a real SAP system, RFC, or OData gateway.
- Seed data is fictional (Northwind / Contoso / Litware / Fabrikam / Adventure Works).
- `env.example` documents `SAP_CONSOLE_URL` (default `http://127.0.0.1:8766/`).
- Never enqueue computer use for `sql-prod-primary`, `sap-customer-directory`, or `sap-hr-payroll`.
- Filter `GET /console/state` bindings to non-`sap-*` ids.
- Tests must not call the live Gemini API.
- Spec: `docs/superpowers/specs/2026-09-19-sap-mock-console-design.md`

## File map

- Modify: `shared/schemas.py` — additive SAP `ResourceType` values
- Modify: `usecase-demo/seed_data.py` — five SAP resources + approvers
- Modify: `policy-engine/engine.py` — `_sap_decision` via `_surface_decision`
- Modify: `tests/test_engine.py` — SAP deny / fall-through tests
- Modify: `agent-runtime/mcp_server.py` — three display `TOOL_SPECS`
- Modify: `agent-runtime/tests/test_mcp_server.py`
- Modify: `agent-runtime/gemini_parser.py` — `hint_resource_ids` + prompt names
- Modify: `agent-runtime/tests/test_parser.py`
- Modify: `backend-api/main.py` — `/sap/state`, console-state filter, enqueue routing
- Modify: `backend-api/tests/test_console_state.py`
- Create: `backend-api/tests/test_sap_state.py`
- Create: `agent-runtime/mock_sap/__init__.py`, `server.py`, `index.html`
- Create: `agent-runtime/tests/test_mock_sap.py`
- Modify: `agent-runtime/computer_use.py` — SAP goals, URL routing, Playwright verbs
- Modify: `agent-runtime/tests/test_computer_use.py`
- Modify: `generative-ui/src/aperture/Menu.tsx`, `Users.tsx`, `User.tsx`, `Summary.tsx`
- Modify: `env.example`

---

### Task 1: Types, seed, and SAP policy deny

**Files:**
- Modify: `shared/schemas.py`
- Modify: `usecase-demo/seed_data.py`
- Modify: `policy-engine/engine.py`
- Modify: `tests/test_engine.py`

**Interfaces:**
- Produces: `ResourceType.SAP_BUSINESS_PARTNER` (`sap_business_partner`), `SAP_BILLING_DOCUMENT` (`sap_billing_document`), `SAP_SALES_ORDER` (`sap_sales_order`), `SAP_CUSTOMER_DIRECTORY` (`sap_customer_directory`), `SAP_HR_PAYROLL` (`sap_hr_payroll`)
- Produces: seed ids `sap-bp-display`, `sap-billing-display`, `sap-sales-order-display`, `sap-customer-directory`, `sap-hr-payroll` with `project="atlas-migration"`
- Produces: `_sap_decision(request, resource, policy, peer_metadata) -> PolicyDecision | None`

- [ ] Add enum values and five seed resources (finance-owned restricted BP/billing; data-platform internal sales order; critical directory/payroll with capability `export` / `admin`)
- [ ] Seed metadata: company `1000`, customer `1710001` (display rows), roles `SAP_SD_CUST_DISPLAY` / `SAP_SD_BILL_DISPLAY` / `SAP_SD_SO_DISPLAY` / `SAP_SD_CUST_EXPORT`, activity `03` or `16`
- [ ] Approvers: finance-owned SAP → Jordan + Priya; sales order → Priya only
- [ ] `_sap_decision` auto-denies `SAP_CUSTOMER_DIRECTORY` and `SAP_HR_PAYROLL` with reason containing `Conduct-SAP-01`; other SAP types return `None` and fall through existing tier rules
- [ ] Call `_sap_decision` from `_surface_decision` (same hook as PowerBI / GitHub). Do not change `_evaluate_level_*`, `DEFAULT_POLICY`, or GCP/GitHub/PowerBI branches
- [ ] Tests in `tests/test_engine.py`: directory/payroll deny; BP restricted cross-team escalates; sales-order same-team internal auto-grants
- [ ] Commit

### Task 2: MCP tools and parser hints

**Files:**
- Modify: `agent-runtime/mcp_server.py`
- Modify: `agent-runtime/tests/test_mcp_server.py`
- Modify: `agent-runtime/gemini_parser.py`
- Modify: `agent-runtime/tests/test_parser.py`

**Interfaces:**
- Produces: `hint_resource_ids(raw_text: str, known: list[str]) -> list[str]`
- Produces: tools `sap_display_bp_1710001`, `sap_display_billing_northwind`, `sap_display_sales_order_northwind`

- [ ] `TOOL_SPECS` for the three display ids only — never `sap-customer-directory` or `sap-hr-payroll`
- [ ] Keyword hints, longer needles first: export all / export customer / customer directory / all customers → `sap-customer-directory`; payroll → `sap-hr-payroll`; billing → `sap-billing-display`; sales order → `sap-sales-order-display`; northwind / 1710001 / customer master / business partner → `sap-bp-display`
- [ ] Do not match the phrase “full customer file” as an export
- [ ] Merge hints into `parse_request` after `constrain_resource_ids`
- [ ] Atlas text still maps only to GCP ids
- [ ] Commit

### Task 3: Hub SAP state and enqueue routing

**Files:**
- Modify: `backend-api/main.py`
- Modify: `backend-api/tests/test_console_state.py` (only if a test breaks)
- Create: `backend-api/tests/test_sap_state.py`
- Modify: `env.example`

**Interfaces:**
- Produces: `GET /sap/state` → `{resources, bindings}` with `role`, `company_code`, `customer_id`, `activity`, `expires_at`, `grant_id`, `principal`, `resource_id`
- Produces: `POST /sap/export-demo` → `{status: "bounced", grant_id: null}` and an `ACTION_EXECUTED` bounce
- Produces: `_console_url_for(grant) -> str`
- Produces: `NEVER_ENACT_IDS = frozenset({"sql-prod-primary", "sap-customer-directory", "sap-hr-payroll"})`

- [ ] Filter `/console/state` bindings to non-`sap-*`; resource catalog may still list all seed resources
- [ ] `/sap/state` only `sap-*` active grants; role/company/customer from resource metadata
- [ ] `_enqueue_execute` skips `NEVER_ENACT_IDS` and uses `SAP_CONSOLE_URL` or `http://127.0.0.1:8766/` for `sap-*`
- [ ] Document `SAP_CONSOLE_URL` in `env.example`
- [ ] Tests: sap bindings, console-state filter, enqueue skip, export-demo bounce, sales-order auto-grant + directory deny via `_evaluate_request`
- [ ] Commit

### Task 4: Mock SAP Fiori console

**Files:**
- Create/finish: `agent-runtime/mock_sap/__init__.py`, `server.py`, `index.html`
- Create: `agent-runtime/tests/test_mock_sap.py`

**Interfaces:**
- Hash routes: `#launchpad`, `#users`, `#bp`, `#bp/1710001`, `#billing`, `#sales`, `#export`, `#payroll` (payroll must not navigate; stay on launchpad)
- DOM contracts: `#active-grants` (`data-resource`, `data-principal`), `#sap-auth-error` with `class="visible"` when shown, `[data-bp="1710001"]`, `[data-tile]`, `#auth-strip`
- Server: `serve_in_thread(host="127.0.0.1", port=8766)` same pattern as `mock_console/server.py`
- Form: `#principal`, role, `#company-code`, `#customer-id`, `#valid-to`, `aria-label="Save role"`, `aria-label="Confirm revoke"`

- [ ] Realistic Fiori Horizon / Quartz Light shell (Helios Manufacturing, company 1000 London, tiles, object pages). Blue `#0070F2` or close SAP blue. Must not look like Google Cloud
- [ ] Working tiles: Customer Master, Billing, Sales Orders, Maintain Business Users. Export clickable (restricted). Payroll locked / not clickable
- [ ] Grant/revoke on Maintain Business Users writes `#active-grants` rows
- [ ] BP 1710001 visible only with a binding; others redacted; opening a restricted BP or Export shows `#sap-auth-error`
- [ ] Hydrate from `GET {backend}/sap/state` via `?backend=` or `window.SAP_BACKEND`
- [ ] Seeded fake partners: 1710001 Northwind, 1710002 Contoso, 1710044 Litware, 1710108 Adventure Works, 1710200 Fabrikam
- [ ] Tests assert chrome strings and DOM contracts; server serves index
- [ ] Commit (do not commit recordings)

### Task 5: Computer use SAP verbs

**Files:**
- Modify: `agent-runtime/computer_use.py`
- Modify: `agent-runtime/tests/test_computer_use.py`

**Interfaces:**
- Produces: `console_url_for(grant: Grant) -> str`
- Produces: `sap_grant_goal(grant)`, `export_goal()`, `verify_sap_export_blocked(html: str) -> bool` (require `class="visible"`, not the CSS selector text), `verify_sap_bp_visible(html: str, bp: str = "1710001") -> bool`
- Playwright: `_enact_sap_grant_on_page`, `_enact_sap_export_on_page`
- `enact_goal(grant, "export")` → `export_goal()`
- `grant_goal` for `sap-*` uses Fiori instructions, not GCP Permissions
- `extra_console_hosts` includes `SAP_CONSOLE_URL`
- Export completed event: `grant_id=None`, `payload.status="bounced"`

- [ ] Playwright grant + export-bounce tests against `mock_sap` (no Gemini)
- [ ] Existing GCP Playwright grant/revoke tests still pass
- [ ] Commit

### Task 6: Aperture presenter controls

**Files:**
- Modify: `generative-ui/src/aperture/Menu.tsx`
- Modify: `generative-ui/src/aperture/Users.tsx`
- Modify: `generative-ui/src/aperture/User.tsx`
- Modify: `generative-ui/src/aperture/Summary.tsx`

**Interfaces:**
- Produces: `SAP_ASK`, `SAP_EXPORT`, `requestSapAsk()`, `requestSapExport()`
- Atlas `ASKS` strings must remain byte-for-byte unchanged
- `SAP_ASK`: resource `sap-bp-display`, 3 days, ticket `INC-8841`, text exactly: `I need display on Northwind Trading customer 1710001 in SAP Customer Master to answer INC-8841. I do not need the full customer file.`
- `SAP_EXPORT`: posts `sap-customer-directory` with ticket `INC-8841`, then `POST /sap/export-demo`

- [ ] Demo menu actions + Alex “Ask SAP” button; Atlas Ask stays
- [ ] Summary guides for the five SAP types
- [ ] User typed-ask matching recognizes northwind / 1710001 / customer master / export
- [ ] Commit
