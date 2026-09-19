# policy-engine

**Owner: contributor 3.** The deterministic core. No model calls in this folder, ever —
that's the security answer to every judge question. Design brief:
[`docs/ui-surfaces.html`](../docs/ui-surfaces.html) (surfaces 5, 8, 9 and "the one rule").

## Plain-English breakdown

### 1. The Policy Engine (The "Automated Guard")

The Policy Engine is an automated decision-maker designed to **handle 90–95% of access
requests instantly**, with zero human involvement. It acts like an extremely fast,
consistent guard standing at the door of your infrastructure.

**What it checks.** When someone asks for access, the Policy Engine runs a quick,
objective checklist:

- **Who are you?** Are you an active employee? Did you log in with strong,
  hardware-based multi-factor authentication (MFA)?
- **How safe is your device?** Is your laptop managed, secure, and running required
  security software?
- **What are you asking for?** Is it a safe environment (like a test server) or a
  sensitive one (like a live customer database)?
- **Why do you need it right now?** Do you have an active ticket assigned to you, or
  are you on call responding to a live incident?

**What decisions it makes.**

- **Auto-Approve** — if the checks pass and the request makes sense (e.g., you're on
  call and need to look at a system during an outage), it instantly gives you
  **temporary access** that automatically expires after a few hours.
- **Hard Deny** — if basic security checks fail (e.g., your laptop isn't up to code or
  your security risk score is sky-high), it blocks the request immediately.
- **Escalate** — if the request is for something critical and lacks automated proof
  (e.g., asking for root database access without an attached ticket), it hands the
  request off to the Escalation Engine.

### 2. The Escalation Engine (The "Smart Dispatcher")

The Escalation Engine takes over **only when the automated Policy Engine isn't 100%
sure** it should approve a request. Instead of making the decision itself, it
translates the technical security request into a clear message for a human manager
and manages the approval process.

**What it does.**

- **Summarizes the Context** — strips away raw code and security logs, summarizing the
  request into a simple 3-bullet Slack or Teams message: who wants access, what they
  want access to, and why the computer couldn't approve it automatically.
- **Finds the Right Approver** — figures out who needs to make the call (e.g., routing
  a database request to the Lead Database Administrator, or an emergency request to
  the On-Call Security Lead).
- **Enforces a Timer (SLA)** — puts a clock on the request:
  - **During an outage:** the manager gets 30 minutes to respond. If no one responds,
    it triggers a temporary "break-glass" emergency access to keep the company
    running, but alerts executives.
  - **During normal ops:** it gives a 4-hour deadline. If no manager approves it in
    time, it automatically denies the request to prevent open access requests from
    sitting idle.

### How they work together

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

> Implementation note: `engine.py` and `escalation.py` already cover most of this (hard
> deny, step-up auth, ticket/incident-aware grants, SLA deadlines). Known gaps against
> this description: the CRITICAL tier's incident-override path is currently unreachable
> because `DEFAULT_POLICY.always_escalate_tiers` still escalates it unconditionally, and
> `apply_timeout()`'s SLA break-glass behavior isn't wired into `backend-api` yet — see
> the "Ambition ladder" and build order below.

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
