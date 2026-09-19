# Demo script — Project Atlas onboarding

Cast: **Alex Chen** (new hire, `data-platform`), **Priya Nair** (Alex's manager),
**Jordan Lee** (Finance data owner).

1. **Request.** Show Alex's coding agent sending `GOLDEN_PATH_REQUEST_TEXT`
   (`seed_data.py`) into the system — either a chat box in `generative-ui` or a curl/CLI
   against `backend-api` if the UI isn't ready yet.
2. **Parse.** `agent-runtime` (Gemini) turns it into an `AccessRequest` naming
   `bucket-analytics-raw` + `bq-project-x-finance`, 14-day duration. Show the structured
   JSON on screen briefly — makes the "LLM proposes, engine decides" point concrete.
3. **Decide.** `policy-engine` evaluates both:
   - `bucket-analytics-raw`: internal tier, same team, 14d ≤ 30d limit → **auto-grant**.
   - `bq-project-x-finance`: restricted tier + cross-team (`data-platform` → `finance`)
     → **escalate**, needs Jordan + Priya.
4. **Live UI update.** `generative-ui` dashboard for Alex shows the bucket panel appear
   immediately; a "pending approval" chip on the dataset.
5. **Approval queue.** Switch to Priya's view: the pending request with the agent's
   plain-English reasoning. Approve. Switch to Jordan's view, approve.
6. **Execute.** `agent-runtime` (computer-use) visibly drives the mock console to action
   both grants — this is the moment to slow down and let it play out on screen.
7. **Audit trail.** Show the full `AuditEvent` timeline for this one request: received →
   evaluated → escalated → votes cast → granted → executed. This is the "we'd trust this
   in production" close.
8. **Revoke.** Trigger "Project Atlas closed" (or fast-forward the TTL) — both grants
   auto-revoke, panels vanish from Alex's dashboard, audit trail logs the revocation.

## Stretch, if time remains

- A second requester whose request gets **auto-denied** (e.g. asking for
  `sql-prod-primary` with a 60-day duration) to show the "no" path exists too.
- A live "time until expiry" countdown on grant panels in `generative-ui`.
- Real GCS bucket IAM binding behind `sql-prod-primary`'s mock, swapped in only if the
  mocked flow is rock solid first.

## Running it locally

Once `backend-api` exposes endpoints, this scenario should be loadable via a seed
script/endpoint that inserts `REQUESTER`, `MANAGER`, `FINANCE_OWNER`, and `RESOURCES`
from `seed_data.py` before the demo starts. Coordinate the exact loading mechanism with
contributor 5.
