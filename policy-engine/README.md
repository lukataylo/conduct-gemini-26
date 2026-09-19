# policy-engine

**Owner: contributor 3.** The deterministic decision core — no LLM calls happen in this
folder, on purpose. Gemini/Claude explain and parse elsewhere; this is the part that has
to be boringly predictable and easy to audit.

## What's here

- `engine.py` — `evaluate_request(request, resources, policy) -> list[PolicyDecision]`.
  Given an `AccessRequest` and the resources it names, returns one decision per resource:
  auto-grant, auto-deny, or escalate. Ships with a working `DEFAULT_POLICY` so this is
  runnable on day one, not a stub.
- `escalation.py` — turns an `ESCALATE` decision into an `EscalationCase`, and resolves
  incoming `ApprovalVote`s into `pending -> approved/denied` (N-of-M: any denial denies,
  all required approvers voting yes approves).

## What's intentionally NOT here

- Resolving *who* the required approvers actually are (team owner lookup, manager
  lookup) — that needs org data, which lives in `usecase-demo`'s seed data and gets
  wired together in `backend-api`. `PolicyDecision.required_approver_ids` is left empty
  by `_escalate()` with a `TODO` — fill it in once `backend-api` can pass in the
  resource→approvers mapping.
- Persistence — this module is pure functions over Pydantic models in, models out.
  `backend-api` owns storing `Grant`/`EscalationCase`/`AuditEvent`.
- TTL expiry sweeping (turning an expired `Grant` into a revoked one on a timer) — that's
  a `backend-api` scheduler concern; this module just sets `expires_at` when asked to
  (add a `build_grant()` helper here if useful once that's wired up).

## Next steps for contributor 3

1. Write a `tests/test_engine.py` covering: same-team auto-grant, cross-team escalate,
   over-duration escalate, critical-tier always-escalate.
2. Decide the real approver-resolution shape with contributor 5 (backend-api) — likely
   `resource.owning_team -> [approver_id, ...]` from `usecase-demo` seed data, plus
   optionally the requester's `manager_id` for cross-team cases.
3. Tune `DEFAULT_POLICY` numbers against whatever `usecase-demo` scenario contributor 4
   is building, so the golden-path demo actually produces one auto-grant + one escalate.

```bash
cd policy-engine
pip install -r requirements.txt
python -c "from engine import evaluate_request, DEFAULT_POLICY; print(DEFAULT_POLICY)"
```
