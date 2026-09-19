# Policy-Based User Case Demo

## Final Story: The Friday Finance Freeze

Project Atlas is a deterministic just-in-time access system. The LLM may parse or
explain a request, but the policy engine decides access using auditable Python rules.

It is Friday afternoon before earnings week. Alex, a platform engineer, is helping the
finance systems team investigate a dashboard outage. Alex and Alex's AI coding agent ask
for access across normal engineering tools, finance systems, BI data, customer support,
warehouse devices, and secrets.

The demo proves Project Atlas is not a one-time approval gate. It is a continuous
governance loop: safe access is granted quickly, risky access escalates with evidence,
dangerous access is denied, and stale access is reclaimed automatically when business
context changes.

## Policy Engine Coverage

### Identity And Context

- Inactive users or stale HR heartbeat are hard-denied.
- Requests need a ticket or incident ID.
- Weak auth returns `STEP_UP_AUTH_REQUIRED`.
- High-risk users or non-compliant devices are denied.
- Too many requested or active resources escalates to `VP_ENG`.

### Capability And Surface Rules

- Same-team internal read access can auto-grant.
- Cross-team, restricted, and critical access escalates.
- Destructive actions are upgraded to critical risk.
- GitHub admin/main-branch access is hard-denied.
- PowerBI `VIEW` grants, while `EXPORT` escalates to Data Steward.
- PII data adds `DISABLE_EXPORT`.
- Payment rails require `WITNESS_REQUIRED`.
- Warehouse IoT requires physical geofence presence.
- Support impersonation requires Zendesk requester/customer match.
- Build pipeline access escalates after recent critical security findings.
- Vault secret harvesting is denied with anomaly alarm.

### Reaper Loop

`review_active_grants(...)` reviews active grants against live business signals and
returns `RevocationAction` objects when access should be reclaimed early:

- HR status becomes non-active.
- Jira/PagerDuty justification is closed.
- Finance quiet period starts and the grant is `write`.
- Warehouse IoT user leaves the geofence.

## Demo Beats

1. **Safe internal access**
   Alex has Jira `ATLAS-101` and asks for internal runbook read access. Atlas grants it
   with a TTL.

2. **PowerBI separation**
   Alex can view the revenue dashboard. Exporting the dataset escalates to the Data
   Steward and carries `DISABLE_EXPORT`.

3. **Finance quiet-period lock**
   Alex asks for finance production write access during earnings quiet period. Atlas
   downgrades the access to read-only and escalates to the CFO with `SOX-404`.

4. **Warehouse geofence deny**
   A seasonal contractor tries to control warehouse IoT scanners from home. Atlas
   denies the request because physical presence is required.

5. **Support impersonation mismatch**
   Alex tries to impersonate a customer, but the Zendesk ticket requester does not match
   the target customer. Atlas hard-denies the request.

6. **Secret harvesting alarm**
   Alex already has three recent vault-secret grants and asks for a fourth. Atlas denies
   it with an anomaly alarm.

7. **Evidence-based escalation**
   The approval card shows policy violation, risk score, peer signal, suggested
   downgrade, required approvers, and SLA.

8. **Reaper closing beat**
   The presenter marks Jira `ATLAS-101` as `DONE`. The Reaper loop returns a
   `RevocationAction` for Alex's finance grant before TTL expiry.

   UI toast:

   ```text
   Access reclaimed: Jira ATLAS-101 is complete.
   ```

## Where it lives (built 19 Sep)

- **Backend:** `GET /demo/policy/final-story` (`backend-api/policy_demo.py`) runs all
  eight beats through the real engine on a fixed clock (2026-09-19 15:00 UTC) and
  returns the request, `PolicyDecision`s, `EscalationCase`s, the Reaper's before/after
  `RevocationAction`s, and the success criteria below evaluated against that output.
  Read-only: no store writes, no audit events, no model calls.
- **Frontend:** the **Policy** tab in the console (`generative-ui/src/aperture/Policy.tsx`),
  reachable from either role. Beat 8 has a *Mark ATLAS-101 DONE* toggle that swaps the
  server-computed before/after states; the toast text comes from the payload.
- **Test:** `python3 -m pytest tests/test_policy_demo.py` fails if any criterion stops
  holding on the engine's output.

## Backend Test Prompt

```text
Create a deterministic final-demo endpoint:

GET /demo/policy/final-story

Seed:
- Alex active employee
- seasonal contractor outside warehouse geofence
- internal runbook bucket
- PowerBI revenue dataset with has_pii=true
- finance production database with surface=FINANCE_PROD
- warehouse IoT scanner with geofence_center
- support impersonation tool
- vault secrets secret-1 through secret-4
- active finance DB grant linked to Jira ATLAS-101
- three active recent secret grants

Context:
- company_calendar.quiet_period covers the demo date
- zendesk has matching and mismatching tickets
- jira has ATLAS-101 as IN_PROGRESS, then DONE
- hr_system has active and leaver identities

Return:
- request payload
- PolicyDecision list
- EscalationCase list when applicable
- RevocationAction list for Reaper scenarios

Never call an LLM from policy evaluation.
```

## Frontend Test Prompt

```text
Build a scenario-driven policy demo page.

Scenarios:
- Safe Internal Access
- PowerBI View vs Export
- Earnings Quiet Period
- Warehouse Geofence Deny
- Support Impersonation Mismatch
- Secret Harvesting Alarm
- Evidence-Based Escalation Card
- Reaper: Jira ATLAS-101 Done -> Auto-Revoke

For each scenario display:
- requester
- resource
- capability
- ticket/incident context
- decision outcome
- exact policy reason
- compliance breadcrumbs
- context snapshot

For the Reaper scenario, show the active finance grant first. Then simulate Jira
ATLAS-101 becoming DONE and show the grant turning red or disappearing with:
"Access reclaimed: Jira ATLAS-101 is complete."
```

## Frontend Success Criteria

- Safe internal access auto-grants.
- PowerBI view grants and export escalates.
- Finance write during quiet period escalates to CFO and becomes read-only.
- Warehouse IoT access from outside the geofence is denied.
- Support impersonation mismatch is denied.
- Secret harvesting is denied with anomaly alarm.
- Escalation card shows risk, violation, peer signal, downgrade, approvers, and SLA.
- Reaper revokes the finance grant when Jira `ATLAS-101` is marked `DONE`.
- The UI clearly shows: AI can parse; deterministic policy decides.
