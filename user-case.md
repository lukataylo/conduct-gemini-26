# Project Atlas User Case Demo

## One-Line Pitch

Project Atlas is a just-in-time access system for modern engineering teams. It lets safe
work move fast, but blocks, escalates, or revokes dangerous access before it becomes a
Cisco-style offboarding incident, a Capital One-style blast-radius incident, or a
regulated-data compliance failure.

## What The Policy Engine Includes

The policy engine is the deterministic security core. It never calls an LLM. LLMs may
parse natural language into structured requests, but every grant, deny, escalation,
witness requirement, and revocation recommendation comes from typed Python rules.

### Core Guards

- **Employment heartbeat:** inactive users or stale HR syncs are hard-denied.
- **No context, no access:** requests need a ticket or incident ID.
- **Device and risk checks:** non-compliant devices and high user risk are denied.
- **Blast-radius protection:** too many requested or active resources escalates to
  `VP_ENG`.
- **Capability escalation:** destructive actions are upgraded to critical risk.
- **On-call velocity:** active incidents allow short-lived fast access.
- **AI agent controls:** agents get session-bound TTLs and scraper-like behavior is
  denied.

### Enterprise Surfaces

- **GitHub:** new-hire access to critical repos escalates; admin/main branch access is
  hard-denied.
- **PowerBI:** `VIEW` can auto-grant; `EXPORT` and `POWER_QUERY` escalate to Data
  Steward; PII decisions include `DISABLE_EXPORT`.
- **Finance:** quiet periods downgrade write access to read-only and escalate to CFO.
- **Payment rails:** require `WITNESS_REQUIRED` with two authorized humans.
- **Warehouse IoT:** physical geofence is enforced.
- **Support impersonation:** Zendesk ticket requester must match the target customer.
- **Build pipelines:** recent critical security-scan findings escalate to Security
  Architect.
- **Vault secrets:** secret harvesting triggers hard deny and anomaly alarm.

### Adversarial Defense

- **5x rejection rule:** repeated denied attempts lock the user, then escalate to SOC.
- **Cross-pollination risk:** risky combinations of grants escalate as correlation risk.
- **Peer signal:** approval cards show whether the request is unusual for the team.

### Reaper Continuous Governance Loop

The Reaper loop makes Project Atlas self-cleaning. It reviews active grants against live
business signals and recommends early revocation before TTL expiry:

- HR status changes revoke all grants for inactive, suspended, or leaver identities.
- Closed Jira tickets or resolved PagerDuty incidents revoke the access they justified.
- Finance quiet periods reclaim write access to finance production systems.
- Warehouse IoT grants are revoked when the user leaves the physical geofence.

This proves Atlas is event-driven, not just time-driven. It watches the state of the
business, not only the clock.

## Final Presentation Demo Story

### Title

**The Friday Finance Freeze**

### Relatable Story

It is Friday afternoon before earnings week. Alex, a platform engineer, is helping the
finance systems team investigate a dashboard outage. Alex and Alex’s AI coding agent ask
for several types of access:

1. Internal runbook bucket read access.
2. PowerBI revenue dashboard view access.
3. PowerBI dataset export access.
4. Finance production database write access.
5. Warehouse IoT scanner control from home.
6. Customer impersonation using a Zendesk ticket.
7. A fourth vault secret in under an hour.

The demo shows that Project Atlas understands who Alex is, what Alex is asking to do,
why the access is needed, whether the company is in a finance quiet period, whether the
user is physically on-site, and whether the request pattern looks suspicious.

### Demo Beats

1. **Safe work moves fast.** Internal read access with a valid ticket auto-grants with
   an expiry.
2. **BI view is allowed, export is not rubber-stamped.** PowerBI `VIEW` grants, but
   `EXPORT` escalates to Data Steward with `DISABLE_EXPORT`.
3. **Earnings quiet period protects finance.** Finance production write is downgraded
   to read-only and escalates to CFO with `SOX-404`.
4. **Warehouse control requires physical presence.** A contractor trying to control IoT
   devices from home is hard-denied.
5. **Support impersonation is trust-bound.** If the Zendesk requester does not match the
   target customer, impersonation is denied.
6. **Secret harvesting is stopped early.** A fourth recent secret request is denied and
   marked with anomaly alarm.
7. **Approvers get evidence, not vague asks.** Escalation cards show risk score, policy
   violation, peer signal, suggested downgrade, and approver groups.
8. **Access cleans itself up.** The presenter marks Jira `ATLAS-101` as done. The Reaper
   loop detects that the justification is closed and recommends revoking the Finance DB
   grant immediately.

## Backend Testing Prompt

```text
Implement a deterministic final-demo endpoint or seed script for Project Atlas.

Expose GET /demo/policy/final-story or POST /demo/policy/run.

Seed resources:
- internal runbook bucket
- PowerBI revenue dataset with has_pii=true
- finance production database with surface=FINANCE_PROD
- warehouse IoT scanner with geofence_center
- support impersonation tool
- vault secrets secret-1 through secret-4

Seed requesters:
- Alex, active employee, platform/data team
- seasonal contractor outside the warehouse geofence
- optional AI agent for bot-scraper tests

Seed PolicyEvaluationContext:
- company_calendar.quiet_period covering the demo date
- requester_location for home and warehouse scenarios
- external_signals.zendesk with matching and mismatching tickets
- external_signals.security_scans with a recent critical finding
- external_signals.jira with ATLAS-101 initially IN_PROGRESS, then DONE
- hr_system with active and leaver identities

Seed active_grants:
- three recent vault-secret grants for Alex
- a finance DB write grant linked to ATLAS-101

For each scenario:
- call policy_engine.evaluate_request or review_active_grants
- return raw PolicyDecision or RevocationAction objects
- for escalations, call escalation.open_case and include the EscalationCase
- never call an LLM from policy evaluation
```

## Frontend Testing Prompt

```text
Build a demo view for the Project Atlas final story.

Required scenarios:
- Safe Internal Access
- PowerBI View vs Export
- Earnings Quiet Period
- Warehouse Geofence Deny
- Support Impersonation Mismatch
- Secret Harvesting Alarm
- Evidence-Based Escalation Card
- Reaper: Jira ATLAS-101 Done -> Auto-Revoke

For every scenario show:
- requester identity and role
- resource and capability
- ticket or incident context
- decision outcome
- exact policy reason string
- compliance breadcrumbs
- context snapshot

For auto-grants show TTL/expiry.
For hard-denies show the red deny state and business-risk reason.
For escalations show policy_violation, risk_score, peer signal, suggested downgrade,
required approver groups, and SLA.
For Reaper revocations show the grant disappearing or turning red with:
"Access reclaimed: Jira ATLAS-101 is complete."

The frontend must use deterministic backend responses and must not invent policy results.
```

## Frontend Success Criteria

- Internal read access with a valid ticket becomes an active grant.
- PowerBI `VIEW` grants and `EXPORT` escalates to Data Steward.
- PII decisions show `DISABLE_EXPORT`.
- Finance production write during quiet period becomes read-only and escalates to CFO.
- Warehouse IoT access from outside the geofence is denied.
- Support impersonation is denied when Zendesk requester does not match the target.
- Fourth secret request is denied with anomaly alarm.
- Escalation card shows risk score, policy violation, peer signal, suggested downgrade,
  approver groups, and SLA.
- Reaper closes the loop: when Jira `ATLAS-101` becomes `DONE`, the finance grant is
  revoked before TTL expiry.
- The UI makes clear that the AI can parse or explain, but deterministic policy decides.

## Suggested Presentation Script

1. “Alex has a valid ticket and needs internal runbook access. This is low-risk, so Atlas
   grants it instantly with an expiry.”
2. “Viewing the revenue dashboard is fine. Exporting PII is different, so Atlas escalates
   to the Data Steward and disables export.”
3. “Alex asks to write to finance production during earnings quiet period. Atlas catches
   the SOX risk, downgrades to read-only, and routes to the CFO.”
4. “A contractor tries to control warehouse scanners from home. Atlas checks physical
   location and denies it.”
5. “Support impersonation requires the ticket requester to match the customer. This
   ticket belongs to someone else, so Atlas blocks it.”
6. “Alex asks for a fourth secret in under an hour. Atlas detects secret harvesting and
   raises an anomaly alarm.”
7. “Now the work is done. We mark Jira ATLAS-101 as complete. Atlas does not wait for
   the TTL; the Reaper loop reclaims the Finance DB grant immediately.”
8. “The key point: the AI never grants access. The deterministic policy engine does, and
   the Reaper continuously takes access back when business context changes.”
