# CLAUDE.md — shared context for everyone's Claude

The project is **Aperture**, a dynamic access-scope agent. Use that name in docs, UI
copy, and commit messages. Read the root `README.md` and `shared/README.md` first. This
file records team decisions that aren't obvious from the code.

## Real GCP behind a `REAL_GCP` flag (owner: GCP setup — eddbr)

The mocked GCP world (`usecase-demo/seed_data.py`) is being backed by **real** GCP
resources so grants/revocations become real IAM changes on stage. Rules:

- **The mock is the default and must always keep working.** Real IAM calls only happen
  when `REAL_GCP=true`. If GCP misbehaves during the demo, set `REAL_GCP=false` and the
  demo runs exactly as before. Never make any workstream *require* GCP to run.
- The only integration point is `backend-api/gcp_iam.py` (`grant` / `revoke`, with an IAM
  read-back). `main.py` calls it via `_mirror_to_gcp()` from `_issue_grant()` and
  `revoke_grant()`. Don't scatter `google-cloud-*` calls elsewhere.
- Run with real GCP (demo laptop): `cd backend-api && uvicorn main:app --env-file ../.env`
  with `REAL_GCP=true` in `.env`. Pre-demo check: `.venv/bin/python infra/gcp_smoke_test.py`
  (runs the golden path against real GCP, grants then revokes, prints PASS/FAIL).
- Failures in real IAM calls must be caught and logged as an `AuditEvent`, never crash
  the request — the mock state is still the source of truth for the UI.
- Only `bucket-analytics-raw` and `bq-project-x-finance` are real. `sql-prod-primary`
  (Cloud SQL) stays mocked — it's the auto-deny example and never gets granted.
- Only fake data lives in the demo project. No real customer/company data.

### Live project

Project `lon-agentic26lon-9202`, region `europe-west2` (London). Resources were created by
`infra/gcp_setup.sh` (idempotent). Pass `--location=europe-west2` to `bq` commands.

### Real names differ from the mock names

GCS bucket names are globally unique and BigQuery dataset IDs can't contain hyphens, so
the real names are configured by env var (see `.env.example`), not hardcoded:

| Mock resource id | Real resource | Env var |
|---|---|---|
| `bucket-analytics-raw` | `gs://<project>-analytics-raw` | `GCS_BUCKET_ANALYTICS_RAW` |
| `bq-project-x-finance` | `<project>.project_x_finance` | `BQ_DATASET_PROJECT_X_FINANCE` |

### Identities

- `alex-chen-agent@<project>.iam.gserviceaccount.com` — "Alex's coding agent". The
  principal that receives task-scoped grants. It holds `roles/bigquery.jobUser` at
  project level permanently (lets it *run* queries, grants no data access); all data
  access comes only from grants.
- `access-granter@<project>.iam.gserviceaccount.com` — what backend-api acts as. Can
  change IAM **only** on the two demo resources (least privilege for the access agent
  itself).
- **Hackathon lab account limits (checked 2026-09-19):** it CAN create service accounts
  and change IAM on the bucket and dataset. It CANNOT change project-level IAM, create
  custom roles, impersonate service accounts, or create SA key files (org policy). So:
  - Real grants must target the bucket/dataset IAM directly, never project-level roles.
  - `alex-chen-agent` has no `bigquery.jobUser`; demo reads use `bq head` (no query job).
  - Code making real GCP calls needs a Google identity: either run on a laptop with
    `gcloud auth application-default login`, or run *inside* GCP (Cloud Run / a VM) with
    a service account attached. **Railway can't do real GCP calls** — keep `REAL_GCP=false` there.
  - **Decided:** with `REAL_GCP=true`, backend-api runs on the demo laptop using the
    presenter's gcloud login (`access-granter` stays unused; Cloud Run as `access-granter`
    is the "production" answer for Q&A). No VM / proof terminal.
- Never commit credentials; `.env` is gitignored.

### Showing it's real on stage

The dashboard looks identical with the flag on or off, so real grants must be *visibly
verified from Google*: after each real grant/revoke, read back the resource's IAM policy
and emit an `AuditEvent` like "Verified in GCP: alex-chen-agent has objectViewer on
gs://…". Backup: a browser tab on the bucket's Console permissions page, refreshed live.
GCS IAM can take up to ~1–2 min to propagate — rehearse the timing.

## Gemini

Use an AI Studio API key (`GEMINI_API_KEY` in `.env`), not Vertex AI. Ask eddbr for the
key; share it privately, never in git or public chat.

## Console and MCP conventions (owner: track 1 / luka — see docs/console-and-mcp.md)

- The demo beat we protect: **close the project → the agent's next call is refused and
  lands red on the chain** and the lease bar is cut, in the same second. Don't build
  anything that makes that slower or less visible.
- **Claude Code ignores `tools/list_changed`** (anthropics/claude-code#77314, verified
  19 Sep on 2.1.278 in both interactive and `-p`). So `mcp_serve.py` lists the whole
  tool catalog from the start (`APERTURE_STATIC_TOOLS=1`, default) and the grant is
  enforced at call time — a refused call says who the approval is pending with. Set
  `APERTURE_STATIC_TOOLS=0` only for clients that honour the notification.
- `ACTION_EXECUTED` events carry `payload = {"tool", "status": "ok"|"bounced",
  "requester_id"}`; `grant_id` is set when authorised, `null` when bounced. The console
  draws bounces red. The MCP server (`agent-runtime/mcp_serve.py`) writes these; any
  other executor (computer use, real IAM) should too.
- The agent's tool list is derived from grants in exactly one place:
  `agent-runtime/mcp_server.tools_for_grants`. `GET /tools` and the stdio server both
  call it. Add a resource to `TOOL_SPECS` if the agent should get a tool for it.
- One colour per person, assigned in `GET /people` order; **red is never a person** —
  it means denied or bounced.
- Deny / Approve are static chrome in `Approvals.tsx`. Generated layouts must not
  produce decision controls.
- Presenter controls (the demo bar) go through the API so they appear in the chain.
  Nothing on screen is UI-only state.
- `mcp` Python SDK is pinned `<2` in `agent-runtime/requirements.txt`; 2.x renamed the
  server API.
- **Write guard:** when `DEMO_KEY` is set in the hub's env, every non-GET request needs
  `X-Demo-Key: <value>` (the console sends `VITE_DEMO_KEY`, the MCP server sends
  `APERTURE_TOKEN`). Unset = open, for local dev. Set it on the demo laptop — venue wifi
  can reach `POST /demo/seed`, `close`, `vote` otherwise.
- **Hub invariants (from the adversarial review, 19 Sep 15:40):** a decided case takes
  no more votes and never mints a second grant; approvals are capped at 30 days
  (`MAX_APPROVED_DAYS`); closing a project also closes its pending cases; `POST /audit`
  only accepts `action_executed` and never a reserved actor (`policy-engine`,
  `gcp-iam`); a repeat ask returns the lease already held (`already_held: true`);
  resource ids are de-duplicated; duration must be ≥ 1 day; blast-radius escalations
  (`resource_id="multiple"`) route to the manager + finance owner via `APPROVERS`.
- **Every request needs business context** or the engine hard-denies it
  (JIT-Evidence-01): `context.active_jira_ticket` / `active_pagerduty_incident`, or
  `metadata.ticket_id`. The console, the MCP server and the NL path (`NLSubmit.context`)
  send `ATLAS-142` by default. Anything else that builds an `AccessRequest` must too.
