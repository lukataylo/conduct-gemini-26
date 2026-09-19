# Enactment Platform — design

**Status:** implementation spec for mock GCP console actions, Computer Use verbs, and backend hub hardening.  
**Does not replace** the five-beat spine. Aperture `generative-ui/` is out of scope.  
**Policy engine** (pushed 19 Sep, `155a44c`) is the decision core; this work integrates it, it does not rewrite it.

Related: `docs/console-and-mcp.md`, `policy-engine/README.md`, `CLAUDE.md` (JIT-Evidence-01).

## Goal

The mock GCP console becomes an action platform. Gemini Computer Use enacts already-decided grants and revokes (and browse/query) against that console. The backend is the source of truth for grants, policy, clock, and console bindings.

## Policy engine integration (first)

The expanded engine (`policy-engine/engine.py`) is already on `main`. Hub rules:

- Call `evaluate_request(request, resources, policy=LIVE_POLICY, active_grants=active_grants(requester.id), now=now())`. Never invent decisions in `backend-api`.
- Hold one `LIVE_POLICY` (`PolicyRule`) initialized from `policy_engine.DEFAULT_POLICY`. `GET /policy` returns it. No `PATCH` in this spec.
- JIT-Evidence-01: missing `ticket_id` / `incident_id` / `context.active_jira_ticket` / `context.active_pagerduty_incident` is a hard deny. Demo default ticket is `ATLAS-142` (`APERTURE_TICKET`). `_evaluate_request` attaches that ticket when the request has no business context so agent/turn, structured posts, and tests do not silently fail the new gate. Clients that already send a ticket keep theirs.
- `WITNESS_REQUIRED` is treated like `ESCALATE` (already on `main`).
- Do not edit `policy-engine/engine.py` or `tests/test_engine.py`.
- New seed resources (`repo-atlas-ingestion`, `repo-finance-ledger`) appear in `GET /resources` automatically. Mock-console / CU GitHub pages are out of this spec (MCP already has tools). `sql-prod-primary` stays never-MCP.

## Computer Use catalog (closed)

Each verb has a typed goal, a Playwright fallback, and a DOM verify. Gemini never decides access.

1. **Grant access** — product nav → resource → Permissions → Grant access → principal + role + expiry → Save.
2. **Revoke access** — Permissions → Remove on that principal → confirm. Verify row gone.
3. **Browse objects** — Storage → `analytics-raw` → Objects → open `events/2026-09-18.parquet`.
4. **Compose query** — BigQuery → `project-x-finance` → Compose → run read-only SELECT against seed rows.
5. **Inspect IAM** — read-only sanity; `alex-chen-agent` has no project-level data roles.

SQL grant UI may exist; backend never enqueues CU for `sql-prod-primary`.

## Mock console

Hash routes, revoke + confirm, seeded objects + preview, query editor + seed results, hydrate from `GET /console/state`. Keep `#active-grants` and the grant dialog so existing Playwright `verify_active` still works.

## Backend (after policy)

- `GET /console/state` — `{resources, bindings}` from active `GRANTS`.
- `GET /stream` — SSE after every `_audit`.
- Demo clock + sweeper; revoke and close-project enqueue CU `action="revoke"`.
- No `X-Demo-Key` in this spec.

## Constraints

- LLMs never write a Grant.
- `GET /grants` default stays active + unexpired.
- `sql-prod-primary` never in `TOOL_SPECS`.
- `ACTION_EXECUTED` convention stays; additive payload keys only (`action`).
- `REAL_GCP` stays grant/revoke IAM only.
- `mcp` pin stays `<2`. Do not rewrite `mcp_serve.py` except ticket already present.
- Do not commit `env.local`, `.env`, keys, or recordings.
- Do not edit `generative-ui/`.
- Work on `feat/enactment-platform`, not `main`.
