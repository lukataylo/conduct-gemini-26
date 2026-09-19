# Project Atlas User Case Demo

## One-Line Pitch

Project Atlas is a just-in-time access system for modern engineering teams. It lets safe
work move fast, but blocks or escalates dangerous access before it becomes a Cisco-style
offboarding incident, a Capital One-style blast-radius incident, or a regulated-data
compliance failure.

## What The Policy Engine Includes

The policy engine is the deterministic security core. It never calls an LLM. LLMs may
parse natural language into structured requests, but every grant, deny, escalation, and
witness requirement comes from typed Python rules.

### Core Identity And Context Guards

- **Employment heartbeat:** inactive users or stale HR syncs are hard-denied.
- **No context, no access:** requests need a ticket or incident ID.
- **Device and risk checks:** non-compliant devices and high user risk are denied.
- **Step-up auth:** weak auth returns `STEP_UP_AUTH_REQUIRED`.
- **Blast-radius protection:** requests for more than 5 resources, or more than 20 active
  resources held by one requester, escalate to `VP_ENG`.

### Capability And Sensitivity Rules

- Internal same-team read access can auto-grant.
- Cross-team or restricted access escalates to manager and owner.
- Critical access escalates to SecOps and owner.
- Destructive actions such as `delete`, `drop`, `terminate`, and `iam_change` are upgraded
  to critical risk.
- On-call engineers with a live incident get fast 4-hour access.
- AI agents are session-bound and denied if they look like runaway scrapers.

### Multi-Surface Enterprise Rules

- **GitHub:** critical repos requested by new hires escalate to Security Lead; admin or
  main-branch access is hard-denied.
- **PowerBI:** view access can auto-grant; export or Power Query escalates to Data Steward;
  PII datasets include a `DISABLE_EXPORT` restriction.
- **Payment rails:** require witness approval with two authorized humans.
- **Warehouse IoT:** physical geofence is enforced before device-control access.
- **Support impersonation:** Zendesk ticket requester must match the customer being
  impersonated.
- **Build pipelines:** recent critical Snyk/SonarQube findings escalate to Security
  Architect.
- **Vault secrets:** requesting more than 3 unique secrets within 60 minutes triggers an
  anomaly hard-deny.

### Adversarial Defense

- **5x rejection rule:** repeated denied attempts for the same resource trigger a 24-hour
  lock and then SOC escalation.
- **Cross-pollination risk:** combinations of existing and requested grants that could
  de-anonymize data escalate as potential data-correlation risk.
- **Peer signal:** escalation metadata tells the approver how unusual the request is for
  the requester’s team.

### Escalation Engine

The escalation engine turns an `ESCALATE` or `WITNESS_REQUIRED` decision into a human
approval case. It adds:

- human-readable summary,
- routing rationale,
- peer percentile,
- risk score,
- policy violation,
- suggested downgrade such as “Grant READ for 4 hours,”
- SLA deadline,
- N-of-M approval with any-deny veto.

## Final Presentation Demo Story

### Title

**“The Friday Finance Freeze”**

### Relatable Story

It is Friday afternoon before earnings week. Alex, a newly onboarded platform engineer,
is helping the finance systems team investigate a dashboard outage. Alex’s AI coding
agent asks for several kinds of access in one workflow:

1. View the internal runbook bucket.
2. Read a PowerBI revenue dashboard.
3. Export the PowerBI dataset.
4. Write to the finance production database.
5. Control warehouse IoT scanners from home.
6. Impersonate a customer account using a Zendesk ticket.
7. Pull a fourth vault secret.

The demo shows that Project Atlas is not a dumb approval queue. It understands context:
who Alex is, whether Alex is active in HR, what Alex is asking to do, whether there is a
ticket, whether the company is in a finance quiet period, whether Alex is physically at
the warehouse, whether the customer opened the support ticket, and whether this access
pattern looks like secret harvesting.

### Demo Beats

1. **Safe work moves fast.**
   Alex requests internal read access with a valid ticket. The policy engine auto-grants
   temporary access and the UI shows an active grant with an expiry.

2. **BI view is allowed, export is not rubber-stamped.**
   PowerBI `VIEW` auto-grants, but `EXPORT` escalates to the Data Steward and shows
   `DISABLE_EXPORT` for PII.

3. **Earnings quiet period protects finance.**
   Alex asks for write access to finance production during a quiet period. The policy
   engine downgrades the request to read-only and escalates to the CFO with a SOX
   breadcrumb.

4. **Warehouse control requires physical presence.**
   A seasonal contractor tries to control warehouse IoT devices from home. The engine
   hard-denies with “Physical presence required for IoT control.”

5. **Support impersonation is trust-bound.**
   Alex tries to impersonate a customer, but the Zendesk ticket requester does not match
   the target customer profile. The request is hard-denied.

6. **Secret harvesting is stopped early.**
   Alex already has three recent secret grants and asks for a fourth. The policy engine
   hard-denies and raises an anomaly alarm.

7. **Approvers get useful cards, not vague asks.**
   Escalation cards show the policy violation, risk score, peer signal, suggested
   downgrade, and required approver group.

### Why This Story Works

This story is relatable because every company has some version of it:

- an engineer trying to move quickly,
- a finance system that must not be changed during sensitive reporting windows,
- a support team that must not impersonate the wrong customer,
- warehouse or operational devices that should not be controlled remotely,
- dashboards that are safe to view but dangerous to export,
- secrets that should never be harvested in bulk.

The presentation message is simple: **Project Atlas gives developers speed without
giving attackers, stale employees, or runaway agents a path to damage.**

## Backend Testing Prompt

Use this prompt for the backend owner:

```text
Implement a deterministic policy-engine test endpoint or seed script for the Project
Atlas final demo.

Goal:
Exercise policy-engine.evaluate_request against the final presentation story in
user-case.md and return the raw PolicyDecision objects to the frontend.

Requirements:
1. Create seeded resources for:
   - internal runbook bucket
   - PowerBI revenue dataset with has_pii=true
   - finance production database with surface=FINANCE_PROD
   - warehouse IoT scanner with a geofence_center
   - support impersonation tool
   - vault secrets: secret-1 through secret-4
2. Create seeded requester profiles:
   - Alex, active employee, data-platform team
   - seasonal contractor located outside the warehouse geofence
   - optional AI agent requester for bot-scraper tests
3. Add a deterministic PolicyEvaluationContext containing:
   - company_calendar.quiet_period covering the demo date
   - requester_location for home and warehouse scenarios
   - external_signals.zendesk with one matching and one mismatching ticket
   - external_signals.security_scans with a recent critical finding
4. Add active_grants for:
   - three recent vault-secret grants for Alex
   - any grants needed for peer/correlation signals
5. Expose either:
   - POST /demo/policy/run with scenario_name, or
   - GET /demo/policy/final-story returning all scenario results.
6. For escalation decisions, call escalation.open_case and include the generated
   EscalationCase fields in the response.
7. Never call an LLM from backend policy evaluation.

Expected response shape:
{
  "scenario": "finance_quiet_period",
  "request": {...},
  "decisions": [...],
  "escalation_cases": [...]
}
```

## Frontend Testing Prompt

Use this prompt for the frontend owner:

```text
Build a demo view for the Project Atlas final policy-engine story.

Goal:
Let judges click through the final user-case.md story and see how each access request is
granted, denied, escalated, or witness-required.

Required UI:
1. A scenario selector with these demo beats:
   - Safe Internal Access
   - PowerBI View vs Export
   - Earnings Quiet Period
   - Warehouse Geofence Deny
   - Support Impersonation Mismatch
   - Secret Harvesting Alarm
   - Evidence-Based Escalation Card
2. For each scenario, show:
   - requester identity and role
   - resource and capability requested
   - ticket or incident context
   - decision outcome
   - reason string from PolicyDecision
   - compliance breadcrumbs
   - context snapshot
3. For auto-grants, show:
   - TTL / expiry
   - restrictions such as DISABLE_EXPORT
4. For hard-denies, show:
   - red deny state
   - exact business-risk reason
   - audit tags / anomaly alarm if present
5. For escalations, render an approval card showing:
   - policy_violation
   - risk_score
   - peer_percentile / peer_signal
   - suggested_downgrade
   - required_approval_groups
   - SLA deadline if backend returns an EscalationCase
6. For witness-required payment rail, show:
   - WITNESS_REQUIRED state
   - two-human approval requirement
7. The UI must use deterministic backend responses; do not invent policy results in the
   frontend.
```

## Frontend Success Criteria

The final frontend policy-engine test is successful when a judge can see all of these
without reading code:

- **Auto-grant path:** internal read access with a valid ticket becomes an active grant.
- **PowerBI separation:** `VIEW` is granted, `EXPORT` escalates to Data Steward.
- **PII restriction:** PowerBI PII decisions show `DISABLE_EXPORT`.
- **Finance quiet period:** finance production write becomes read-only and escalates to
  CFO with `SOX-404`.
- **Warehouse geofence:** out-of-office warehouse IoT control is hard-denied.
- **Support trust check:** impersonation is denied when Zendesk requester does not match
  the target customer.
- **Secret harvesting:** fourth secret request is denied and marked with anomaly alarm.
- **Evidence card:** escalation card shows risk score, policy violation, peer signal,
  suggested downgrade, and approver groups.
- **Auditability:** every decision displays the exact reason returned by the policy
  engine.
- **No black box:** the UI makes clear that the LLM parsed the request, but the policy
  engine made the security decision deterministically.

## Suggested Demo Script

1. “Alex has a valid ticket and needs internal runbook access. This is low-risk, so Atlas
   grants it instantly with an expiry.”
2. “Now Alex asks to view the revenue dashboard. View is fine. But exporting a PII dataset
   is different, so Atlas escalates to the Data Steward and disables export.”
3. “Alex asks to write to finance production during earnings quiet period. Atlas catches
   the SOX risk, downgrades the request to read-only, and routes it to the CFO.”
4. “A contractor tries to control warehouse scanners from home. Atlas checks physical
   location and denies it.”
5. “Support impersonation requires the ticket requester to match the customer. This
   ticket belongs to someone else, so Atlas blocks it.”
6. “Finally, Alex asks for a fourth secret in under an hour. Atlas detects secret
   harvesting and raises an anomaly alarm.”
7. “The key point: the AI never grants access. The deterministic policy engine does.”
