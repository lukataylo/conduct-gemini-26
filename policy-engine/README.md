# policy-engine

**Owner: contributor 3.** The deterministic core. No model calls in this folder, ever —
that's the security answer to every judge question. Design brief:
[`docs/ui-surfaces.html`](../docs/ui-surfaces.html) (surfaces 5, 8, 9 and "the one rule").

## Current Policy Summary

### The Policy Engine: The Automated Guard

The Project Atlas Policy Engine is a deterministic security gatekeeper that replaces
manual "rubber-stamping" with real-time, logic-based access control. It evaluates the
**Who** (identity and HR status), **What** (resource sensitivity), **How** (capability
like read vs. delete), and **Why** (ticket or incident context) of every request. By
automating low-risk approvals and escalating high-risk anomalies, it ensures access is
granted with the least privilege necessary and can be revoked the moment it is no
longer required.

`engine.py` currently enforces these checks in order:

1. **Employment heartbeat hard deny** — if the requester is inactive or their HR sync
   is older than 24 hours, the whole request is denied before any resource evaluation.
2. **No context, no access** — every request needs a `ticket_id`, `incident_id`,
   `active_jira_ticket`, or `active_pagerduty_incident`; missing business context is a
   hard deny.
3. **Device and user-risk hard deny** — non-compliant devices and user risk scores
   above 70 are denied.
4. **Step-up authentication** — non-phishing-resistant auth returns
   `STEP_UP_AUTH_REQUIRED` instead of granting access.
5. **Blast-radius protection** — requesting more than 5 resources at once, or pushing
   the requester above 20 active resources, escalates to the Engineering VP group.
6. **Capability-based escalation** — destructive capabilities (`delete`, `drop`,
   `terminate`, `iam_change`) upgrade the request to CRITICAL and require security-led
   approval.
7. **Surface-specific policy** — GitHub, PowerBI, payment rails, warehouse IoT, support
   impersonation, build pipelines, vault secrets, and finance production each get their
   own deterministic rules.
8. **Tier, duration, and team policy** — same-team low-risk requests can auto-grant;
   cross-team, over-duration, restricted, or critical requests escalate according to
   `DEFAULT_POLICY`.

The engine returns one deterministic `PolicyDecision` per resource unless a global hard
deny or blast-radius escalation applies. It performs no I/O and makes no model calls.

### Enterprise Sentinel Surface Rules

The engine now handles more than generic cloud buckets and databases:

- **GitHub repositories** — new hires requesting critical repositories escalate to a
  Security Lead; admin and main-branch access is hard-denied because those rights are
  manual-only.
- **AI agents** — agents get session-bound TTLs and are denied if they already hold too
  many active grants or request scraper-like bulk access.
- **PowerBI datasets** — `VIEW` can auto-grant; `EXPORT` and `POWER_QUERY` escalate to
  the Data Steward; PII datasets include `DISABLE_EXPORT`.
- **Payment rails** — return `WITNESS_REQUIRED`; access is only valid with two
  authorized humans.
- **Warehouse IoT** — access requires the requester to be within the physical geofence.
- **Support impersonation** — Zendesk ticket requester must match the customer profile
  being accessed.
- **Build pipelines** — recent critical Snyk/SonarQube findings escalate to Security
  Architect.
- **Vault secrets** — a fourth unique secret within 60 minutes is denied with an
  anomaly alarm.
- **Finance production** — write access during an earnings quiet period is downgraded
  to read-only and escalated to the CFO.

### Adversarial Defense

- **5x rejection circuit breaker** — repeated denied attempts for the same resource
  trigger a hard lock, then SOC escalation.
- **Cross-pollination risk** — combinations of grants that could de-anonymize data
  escalate as potential data-correlation risk.
- **Peer signal** — policy decisions include peer-comparison metadata for approval
  cards, e.g. whether only a tiny fraction of the requester’s team has this access.

### The Escalation Engine: The Smart Dispatcher

`escalation.py` takes over only after the policy engine returns `ESCALATE`. It does not
decide security policy; it manages the human approval workflow:

- synthesizes a concise approval summary,
- records the routing rationale,
- snapshots requester and duration at case-open time,
- enforces 30-minute incident SLAs and 4-hour standard-ticket SLAs,
- applies N-of-M approval rules with any-deny veto,
- ignores votes from non-required approvers.
- carries evidence-card metadata: peer signal, risk score, policy violation, suggested
  downgrade, and original policy metadata.

### The Reaper Loop: Continuous Governance

`review_active_grants(active_grants, resources, context) -> list[RevocationAction]`
turns Project Atlas from a one-time gatekeeper into a self-cleaning access system. It
reviews grants against live business and security signals and recommends early
revocation before TTL expiry.

Reaper triggers:

- **HR purge** — if HR marks a requester as `LEAVER`, `SUSPENDED`, `ON_LEAVE`, or any
  non-`ACTIVE` status, all grants for that requester are revoked.
- **Justification sunset** — if the Jira ticket or PagerDuty incident attached to a
  grant is `DONE`, `RESOLVED`, or `CLOSED`, the grant is revoked immediately.
- **Finance quiet period** — if finance production enters a quiet period, `write` grants
  are reclaimed while read-only access can remain.
- **Geofence breach** — warehouse IoT grants are revoked when the user moves outside the
  authorized physical range.

### How They Work Together

```
[User Requests Access]
         │
         ▼
┌─────────────────────────┐
│     POLICY ENGINE       │ ──(Pass)──> [Instant Access Granted]
│  (Automated Checkup)    │ ──(Fail)──> [Instant Access Denied]
└─────────────────────────┘
         │
    (Unsure / High Risk)
         │
         ▼
┌─────────────────────────┐
│   ESCALATION ENGINE     │ ──> Sends Slack/Teams Card to Manager ──> [Human Approves/Denies]
│   (Smart Dispatcher)    │ ──> Tracks 30m/4h SLA Timer
└─────────────────────────┘
```

- **Policy Engine** does the heavy lifting, checking rules in milliseconds so humans
  don't waste time clicking "Approve" on routine requests.
- **Escalation Engine** keeps human managers in the loop *only* when necessary, giving
  them all the context they need to make a fast, 1-click decision.

## Cisco Case Motivation

### The Cisco Case: A Failure of Offboarding and Oversight

In 2018, former Cisco engineer Sudhish Ramesh resigned from the company, but his access
to their AWS cloud environment remained active. Five months after leaving, he used his
"ghost" credentials to deploy a malicious script that deleted 456 virtual machines
supporting the WebEx Teams application. This unauthorized action caused 16,000 customer
accounts to go dark for two weeks, required a massive manual restoration effort, and
resulted in a 24-month prison sentence for Ramesh.

### The Cost of Failure: $2.4 Million+

The lack of automated access controls resulted in major financial and operational
damage:

- **Operational cost:** $1,400,000 in employee time to rebuild infrastructure and
  restore data.
- **Direct financial loss:** $1,000,000 in refunds and credits issued to affected
  customers.
- **Intangible damage:** severe reputational harm to the WebEx brand and a two-week
  service outage for 16,000 teams.

### How Project Atlas Reflects and Prevents This Case

The tightened policy engine directly addresses the "Ramesh Scenario" through three
technical layers:

- **HR-heartbeat sync** — the policy engine checks HR status and HR sync freshness
  before evaluating resources. The moment an employee is inactive or stale in HR, the
  "Who are you?" check fails. In a full deployment, agent-runtime/backend revocation
  would purge existing cloud permissions, making ghost access impossible.
- **Capability-based escalation** — destructive capabilities such as delete or shutdown
  are treated differently from read access. Even on an internal resource, a destructive
  request is upgraded to CRITICAL and requires multi-party approval including a security
  lead.
- **Just-in-time evidence** — access must be tied to active work through a ticket or
  incident. A former employee attempting access months later would lack valid assigned
  work context, triggering hard deny before any infrastructure action could run.

## Demo Scenarios Covered By Tests

`tests/test_engine.py` covers the final presentation beats:

- Cisco/Ramesh inactive-user hard deny.
- Capital One-style blast-radius escalation.
- On-call velocity auto-grant.
- Destructive internal bucket escalation.
- GitHub new-hire and admin/main-branch rules.
- PowerBI view vs export separation.
- Persistent attacker circuit breaker and SOC escalation.
- Finance quiet-period write downgrade.
- Warehouse geofence hard deny.
- Support impersonation mismatch.
- Payment rail witness requirement.
- Build pipeline critical vulnerability escalation.
- Secret harvesting anomaly alarm.
- Reaper revocation on ticket close, HR termination, finance quiet period, and geofence
  breach.

## What's here

- `engine.py` — `evaluate_request(...) -> list[PolicyDecision]` and
  `review_active_grants(...) -> list[RevocationAction]`.
- `escalation.py` — `open_case()` (snapshots requester + duration), `apply_vote()`;
  votes from non-required approvers are ignored; any deny → denied, all required → approved.

## How To Test

From the repo root:

```bash
python3 -m pytest tests/test_engine.py
```

The suite is intentionally scenario-driven. Each test maps to a demo beat or a security
invariant, so a passing suite means the presentation story is backed by deterministic
rules, not frontend mock text.

## Rules that don't bend

- Pure functions, typed in, typed out. No I/O, no clock reads (take `now` as an argument).
- A decision is reproducible from its inputs. If it isn't, it's a bug.

```bash
cd policy-engine && pip install -r requirements.txt hypothesis && pytest
```
