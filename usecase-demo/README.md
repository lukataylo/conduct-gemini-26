# usecase-demo

**Owner: contributor 4.** Owns the concrete scenario everyone else builds and tests
against, so the other four workstreams have real data to point at instead of guessing.

## What's here

- `seed_data.py` — the Project Atlas scenario: a requester, a manager, a finance data
  owner, three resources spanning `internal`/`restricted`/`critical` tiers, and the exact
  approver mapping per resource. Also the natural-language request text used to kick off
  the golden-path demo.
- `demo_script.md` — the beat-by-beat run of show for the live demo, mapped to which
  workstream is on screen at each step.

## Next steps for contributor 4

1. Sanity-check the scenario against `policy-engine`'s `DEFAULT_POLICY`: run
   `evaluate_request` over `RESOURCES` with a request matching
   `GOLDEN_PATH_REQUEST_TEXT` and confirm it produces exactly one auto-grant + one
   escalate. Adjust either the policy numbers or the resource tiers/teams until it does.
2. Build (or find) whatever "mock GCP console" `agent-runtime`'s computer-use step will
   drive — even a rough static HTML page with buckets/datasets listed and a "Grant
   access" button is enough; it doesn't need real backing data, just something
   Claude can click through convincingly on stage.
3. Work out the seed-loading mechanism with contributor 5 (backend-api) — a startup
   script, a `/seed` endpoint, or a fixtures file `backend-api` reads on boot.
4. Own the actual demo run-through rehearsal — time it, and flag to the other four if any
   step is too slow (especially computer-use) for a live audience.
