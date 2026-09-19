# policy-engine

**Owner: contributor 3.** The deterministic core. No model calls in this folder, ever —
that's the security answer to every judge question. Design brief:
[`docs/ui-surfaces.html`](../docs/ui-surfaces.html) (surfaces 5, 8, 9 and "the one rule").

## Ambition ladder

| | What | Done when |
|---|---|---|
| **Core** (must demo) | Tiers × duration × team → grant / escalate / deny (in repo). N-of-M with any-veto (in repo). `tests/test_engine.py` for the four cases. Approver resolution from `usecase-demo.APPROVERS`. | Golden path: bucket auto-grants, dataset escalates, both approvers, approved. |
| **Ambitious** (wins) | **Cross-resource chaining check**: evaluate the requested *set*, not just each id — read on a restricted dataset + write on a public bucket escalates as a pair (the exfil shape). **Peer-comparison risk signal**: "0 of 6 on data-platform hold this" feeds the approval card. **Hot-reloadable policy** via `GET/PATCH /policy` with validation. **Hypothesis property tests** proving invariants: critical never auto-grants; every grant has an expiry ≤ tier max; deny-any-veto. | Second demo scenario: a chaining attempt is denied with a reason a human can read. Tightening a slider flips a decision live. |
| **Fallback** | `DEFAULT_POLICY` as is. | Already works. |

## What's here

- `engine.py` — `evaluate_request(request, resources, policy) -> list[PolicyDecision]`
  with a working `DEFAULT_POLICY`.
- `escalation.py` — `open_case()`, `apply_vote()`; any deny → denied, all required → approved.

## Build order

1. **Tests first** — `tests/test_engine.py`: same-team internal auto-grants; cross-team
   escalates; over-duration escalates; critical always escalates; unknown id denies.
2. **Approvers** — `_escalate()` takes an `approvers: dict[str, list[str]]` argument
   (resource id → approver ids) instead of the empty list; backend passes
   `usecase_demo.APPROVERS`.
3. **Chaining** — `evaluate_set(request, resources, policy)` runs after per-resource
   decisions: if the set contains a `RESTRICTED`+ read and any write-capable resource
   outside the owning team, escalate every auto-grant in the set with reason
   `"chained: <a> + <b> forms an export path"`. Add a `capability: read|write` field to
   `Resource` in `shared/schemas.py` (additive, tell the others).
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
