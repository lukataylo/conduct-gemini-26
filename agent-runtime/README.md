# agent-runtime

**Owner: contributor 2.** Everything that touches an LLM or drives the mock console
directly, plus the audit-logging helper and the Modal deployment for all of it.

## What's here

- `gemini_parser.py` — `parse_request(raw_text, requester, known_resource_ids) ->
  AccessRequest`. The only place free text becomes structured data. Use Gemini's
  structured-output / `response_schema` mode, constrained to `known_resource_ids`, so it
  can't hallucinate a resource. Skeleton has the prompt and the exact spot to drop in the
  `google-genai` call — see the `TODO` in the file.
- `computer_use.py` — `execute_grant(grant, console_url) -> AuditEvent`. Drives Claude's
  computer-use tool against the mock GCP console from `usecase-demo`/`backend-api` to
  *visibly perform* an already-decided grant. This is the on-stage wow moment — make
  sure it never makes a decision, only executes one policy-engine already approved.
- `audit_logger.py` — `log(type, actor, detail, ...)`. Use this instead of ad-hoc
  logging; call `set_emitter()` once backend-api exposes a real `/audit` endpoint so
  events land in the shared trail instead of just local memory.
- `modal_app.py` — exposes `parse_request` and `execute_grant` as Modal endpoints
  backend-api calls, so slow/computer-use-heavy work doesn't block the API.

## Setup

```bash
cd agent-runtime
pip install -r requirements.txt
modal token new                 # first time only, links your Modal account
modal secret create access-scope-agent-secrets GEMINI_API_KEY=... ANTHROPIC_API_KEY=...
modal serve modal_app.py        # local dev with hot reload
```

## Next steps for contributor 2

1. `gemini_parser.py`: fill in the real `google-genai` structured-output call — the
   prompt and schema shape are already sketched, follow the `TODO`.
2. `computer_use.py`: get one computer-use loop working end to end against *any* web
   page first (even a static mockup), then point it at whatever `usecase-demo` builds as
   the mock console.
3. Decide with contributor 5 (backend-api) whether `execute_grant` should be
   synchronous (backend-api waits) or fire-and-callback (Modal function posts an
   `AuditEvent` back to backend-api when done) — computer-use loops can run long, so
   fire-and-callback is probably safer for the live demo.
4. Wire `audit_logger.set_emitter()` to POST to backend-api's `/audit` endpoint once it
   exists.
