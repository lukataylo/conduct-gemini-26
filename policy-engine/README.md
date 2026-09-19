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
6. **Capability-based escalation** — destructive capabilities (`delete`, `shutdown`,
   `drop`, `terminate`) upgrade the request to CRITICAL and require security-lead
   approval.
7. **Tier, duration, and team policy** — same-team low-risk requests can auto-grant;
   cross-team, over-duration, restricted, or critical requests escalate according to
   `DEFAULT_POLICY`.

The engine returns one deterministic `PolicyDecision` per resource unless a global hard
deny or blast-radius escalation applies. It performs no I/O and makes no model calls.

### The Escalation Engine: The Smart Dispatcher

`escalation.py` takes over only after the policy engine returns `ESCALATE`. It does not
decide security policy; it manages the human approval workflow:

- synthesizes a concise approval summary,
- records the routing rationale,
- snapshots requester and duration at case-open time,
- enforces 30-minute incident SLAs and 4-hour standard-ticket SLAs,
- applies N-of-M approval rules with any-deny veto,
- ignores votes from non-required approvers.

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

## Ambition ladder

| | What | Done when |
|---|---|---|
| **Core** (must demo) | Tiers × duration × team → grant / escalate / deny (in repo). N-of-M with any-veto (in repo). `tests/test_engine.py` for the four cases. Approver resolution from `usecase-demo.APPROVERS`. | Golden path: bucket auto-grants, dataset escalates, both approvers, approved. |
| **Ambitious** (wins) | **Cross-resource chaining check**: evaluate the requested *set*, not just each id — read on a restricted dataset + write on a public bucket escalates as a pair (the exfil shape). **Peer-comparison risk signal**: "0 of 6 on data-platform hold this" feeds the approval card. **Hot-reloadable policy** via `GET/PATCH /policy` with validation. **Hypothesis property tests** proving invariants: critical never auto-grants; every grant has an expiry ≤ tier max; deny-any-veto. | Second demo scenario: a chaining attempt is denied with a reason a human can read. Tightening a slider flips a decision live. |
| **Fallback** | `DEFAULT_POLICY` as is. | Already works. |

## What's here

- `engine.py` — `evaluate_request(request, resources, policy) -> list[PolicyDecision]`
  with a working `DEFAULT_POLICY`.
- `escalation.py` — `open_case()` (snapshots requester + duration), `apply_vote()`;
  votes from non-required approvers are ignored; any deny → denied, all required → approved.

## Build order

1. **Tests first** — `tests/test_engine.py`: same-team internal auto-grants; cross-team
   escalates; over-duration escalates; critical always escalates; unknown id denies.
2. **Approvers** — `_escalate()` takes an `approvers: dict[str, list[str]]` argument
   (resource id → approver ids) instead of the empty list; backend passes
   `usecase_demo.APPROVERS`.
3. **Chaining** — `evaluate_set(request, resources, policy, active_grants)` runs after
   per-resource decisions over the requester's **effective set** (what they'd hold:
   active grants plus requested — so splitting into two requests doesn't help): if it
   contains a `RESTRICTED`+ read and any write-capable resource outside the owning
   team, escalate every auto-grant in the request with reason
   `"chained: <a> + <b> forms an export path"`. `Resource.capability` is already in the
   schema; the bucket in seed data is `write`.
4. **Peer signal** — `peer_comparison(requester, resource, grants) -> str` over seed
   history; pure string, no decision impact tonight, but it's on the card.
5. **Hot reload** — `PolicyRule` is already Pydantic; backend holds one instance; `PATCH`
   validates and swaps it. Tests must still pass on the swapped policy.
6. **Property tests** — Hypothesis strategies over `AccessRequest` + `Resource`; assert
   the three invariants. Run them in the policy-console "propose" flow if contributor 1
   gets there.

## Rules that don't bend

- Pure functions, typed in, typed out. No I/O, no clock reads (take `now` as an argument).
- A decision is reproducible from its inputs. If it isn't, it's a bug.

```bash
cd policy-engine && pip install -r requirements.txt hypothesis && pytest
```
