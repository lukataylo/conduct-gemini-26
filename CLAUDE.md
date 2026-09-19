# CLAUDE.md — shared context for everyone's Claude

Read the root `README.md` and `shared/README.md` first. This file records team decisions
that aren't obvious from the code.

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
