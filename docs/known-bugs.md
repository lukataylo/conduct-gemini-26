# Known bugs (adversarial review, 19 Sep 2026 15:40–16:20)

What the three reviewers found that is **not yet fixed**. Fixed items are listed in
`docs/console-and-mcp.md` under "Adversarial review" and enforced by the hub invariants in
`CLAUDE.md`. Claim one by putting your name after the arrow; delete the line when it's on main.

## Policy engine (owner: policy-engine track)

1. **Reaper never runs.** `engine.review_active_grants` is defined but the hub never calls
   it, so grants are only cut by TTL-on-read, revoke, or project close — nothing re-checks
   device/HR state mid-lease. Fix: a background task in `backend-api/main.py` calling it
   every ~30s and revoking with the engine's reason. → _unclaimed_
2. **Circuit breaker never fires.** `evaluate()` is called without the requester's recent
   request history, so the burst/anomaly gate always sees zero. → _unclaimed_
3. **Peer percentile always "unavailable".** Team sizes aren't passed to the engine.
   Cosmetic on stage, but the reason string mentions it. → _unclaimed_
4. **Ticket id is not validated.** `"  "` or `"x"` in `context.active_jira_ticket` passes
   JIT-Evidence-01. Fix: strip + regex `^[A-Z]+-\d+$` at the engine gate. → _unclaimed_

## Hub / API (owner: backend-api track)

5. **`vote` trusts `approver_id` in the body.** Anyone holding the demo key can vote as
   Priya. The `X-Demo-Key` guard gates the room, not the person. Fix for tonight: none
   needed; for Q&A the answer is "approver identity comes from the IdP session". → _unclaimed_
6. **REST reads are unscoped.** `/audit`, `/escalations`, `/grants?include_revoked=true`
   return everyone's data to any caller. The console needs the full view (manager screen),
   so a per-viewer filter would have to be opt-in via `?viewer_id=`. → _unclaimed_
7. **MCP `APERTURE_TOKEN` is the room key, not an identity.** `mcp_serve.py` picks its
   requester from `APERTURE_REQUESTER` env; the hub does not check that the token matches
   the requester. → _unclaimed_
8. **Six tests fail:** `backend-api/tests/test_agent_turn.py` builds `AccessRequest`s
   without a ticket, so since the policy expansion the engine returns
   `resource_id="all"` (JIT-Evidence-01) and the expected confirm-flow results never
   appear. Fix: add `context={"active_jira_ticket": "ATLAS-142"}` in the fixtures. → _unclaimed_

## Gemini (owner: agent-runtime track)

9. **Date parsing is unreliable.** "until Nov 15" and "done by Nov 15" come back as the
   14-day default instead of the real delta. Fix: give `gemini_parser` today's date in
   the prompt and ask for `requested_until` ISO date, compute days in Python. → _unclaimed_
10. **`list_scope` has no `person_id`.** A manager asking Gemini "what does Alex have?"
    is answered about themselves. Fix: optional `person_id` on the tool, allowed when the
    viewer is a manager/approver. → _unclaimed_

## Not bugs, but say it right on stage

- Grants are **time-bound and revoked on close**, not "continuously reviewed" (see 1).
- The audit chain proves **order and integrity**, not identity — actors on
  `action_executed` events are whatever the MCP server says they are (7).
