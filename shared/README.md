# shared

The contract every other workstream imports. `schemas.py` defines the Pydantic v2
models that cross service boundaries:

- `AccessRequest` — what a requester (or their agent) asked for
- `PolicyRule` / `PolicyDecision` — how the policy engine evaluates a request
- `EscalationCase` / `ApprovalVote` — the in-app approval queue
- `Grant` — an active, scoped, TTL'd access grant
- `AuditEvent` — every state transition, typed, for the audit trail
- `UIComponentSpec` / `UISpec` — what Gemini emits and `generative-ui` renders

## Rules for changing this file

1. If your workstream needs a new field, add it here first, then use it — don't shadow
   it with a local redefinition in your own folder.
2. Additive changes (new optional field, new enum value) are safe to make unilaterally.
   Anything that removes or renames a field, ping the other 4 before merging.
3. Python services import directly: `from shared.schemas import AccessRequest`.
4. `generative-ui` (TypeScript) doesn't import this directly — mirror the shapes you
   actually consume (mainly `UISpec` / `UIComponentSpec`) as TS types in
   `generative-ui/src/types.ts`, kept in sync by hand for the hackathon.

## Setup

No install needed — it's plain Pydantic. Each Python workstream's `requirements.txt`
includes `pydantic>=2`, and imports this package via a relative path
(`sys.path`/`PYTHONPATH` includes the repo root) or `pip install -e ../shared` if you
turn it into a proper local package once things stabilize.
