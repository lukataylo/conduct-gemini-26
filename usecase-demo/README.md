# usecase-demo

**Owner: contributor 4.** The scenario everyone builds against, the console the agent
drives, and the four-minute demo — including owning the rehearsals. Design brief:
[`docs/ui-surfaces.html`](../docs/ui-surfaces.html) ("Build order for tonight", "What a judge will poke at").

## Ambition ladder

| | What | Done when |
|---|---|---|
| **Core** (must demo) | Project Atlas scenario (in repo). **Mock GCP console** page with buckets, datasets, IAM bindings and a "Grant access" form — handed to contributor 5 for the Railway deploy by 13:30. **Presenter panel** at `/demo`: reset seed · submit scenario 1 / 2 · advance clock 14d · close project · replay/live toggle (locked to replay unless the rehearsal flag is set). Five-beat, four-minute script. | Two run-throughs under four minutes, one by someone who didn't build it. |
| **Ambitious** (wins) | **Adversarial second scenario**: a request for `analytics-raw` (write) + `project-x-finance` (read) — each fine alone — is escalated as a chaining risk with a readable reason. **Close-project beat**: one action, panels vanish, tools vanish from Claude Code, trail records it. Peer-comparison seed history so the approval card has something true to say. A recorded fallback video of the whole demo. | The chaining scenario runs in under 30 seconds and the audience understands why it was stopped. |
| **Fallback** | Static console page; static scenario JSON. | — |

## What's here

- `seed_data.py` — requester, manager, finance owner, three resources across
  internal / restricted / critical, `APPROVERS` map, the golden-path request text.
- `demo_script.md` — beat-by-beat run of show.

## Build order

1. **Verify the scenario** against `policy-engine` — one auto-grant, one escalate, from
   the golden-path text. Adjust tiers or numbers until it's exact.
2. **Mock console** — `console/` (plain HTML + a little JS is fine): list resources,
   show IAM bindings from `GET /grants`, a "Grant access" form posting to
   `/grants/execute` — this is what computer use clicks. Big, stable selectors. No
   free text on the page that reads like an instruction (it can steer the agent). Hand
   it to contributor 5 by 13:00 for deploy.
2b. **Presenter panel** — `/demo` route, hidden from the judges' view: the five controls
   above. Every one of them is audited so the trail shows the fast-forward.
3. **Seed history** — 5–10 historical grants across the three teams so peer comparison
   is true ("0 of 6 on data-platform hold `project-x-finance`").
4. **Second scenario** — add `capability` to resources (contributor 3 is adding the
   field); write the request text; confirm the engine escalates the pair.
5. **Script** — update `demo_script.md` with the closing beat (close project → tools
   vanish) and the judge answers. Time it. Record a fallback screen capture at ~18:00.
6. **Rehearsals** — 17:45 and 18:15. You call the 18:30 gate on live computer use.

## Rules that don't bend

- Nothing in the demo is faked. Fast-forwarded clocks and recorded replays are labelled
  on screen with when they happened.
