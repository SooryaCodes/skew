# 05 — Security

Judges read the repo. Security discipline is visible and it scores.

## Secrets

- All credentials via environment variables. `.env` is gitignored; `.env.example`
  is committed with empty values.
- **The Alpaca key never reaches the browser.** The Next.js app talks only to our
  FastAPI backend. No `NEXT_PUBLIC_` variable ever holds a secret — anything with
  that prefix is in the client bundle and readable by anyone.
- Never log a key, even partially. Redact in exception handlers.
- Before uploading the demo video, scrub every frame for a visible key in a
  terminal, an editor, or a browser devtools panel. This is the classic hackathon
  disaster and it is entirely preventable.

## Paper-only enforcement

Hard assertion at startup, before any client is constructed:

```python
if "paper" not in settings.alpaca_base_url:
    raise RuntimeError("SKEW is paper-only. Refusing to start.")
```

There is no live trading code path, no flag, no environment that enables one.
State this explicitly in the README — it's a trust signal, and it costs nothing.

Additionally, verify at startup that the account is the dedicated hackathon
account (check the account number against an env var) and log a warning if the
equity is not approximately $100,000.

## The model is not trusted

The bounded selector is treated as an untrusted component:

- It receives a **serialised list of pre-validated candidates**, nothing more. No
  account access, no API keys, no execution function, no tools.
- Its output is validated against a strict schema: it must return one of the
  candidate IDs it was given, or `ABSTAIN`. Anything else is treated as abstention
  and logged as a malformed response.
- Its free-text rationale is stored and displayed but **never parsed for
  instructions**. Nothing the model writes can change what executes.
- Prompt injection surface: contract data comes from Alpaca, not from user input,
  so the surface is small — but treat any string that reaches the prompt as
  untrusted anyway, and never interpolate unvalidated text into the system prompt.

This design is worth calling out in the video. "The model cannot place a trade;
it can only choose among trades the risk engine already approved" is a strong line.

## Kill switch

- `POST /api/kill` sets `KILL_SWITCH=true`, halting new entries immediately.
- Requires a shared secret header. Not open to the internet unauthenticated.
- On kill: stop opening, continue monitoring existing positions, log the event.
- Also settable by env var so it survives a restart.

## Execution safety

- Every order carries a unique `client_order_id` for idempotency. A retry after a
  network timeout must not double-fill.
- Re-check the gate chain immediately before submission. Market data moves between
  candidate construction and order placement.
- Hard cap on concurrent positions (`MAX_CONCURRENT_POSITIONS`).
- Refuse to open if existing unmanaged positions are found in the account — the
  account must be exclusively ours or the risk math is wrong.

## API surface

- Read endpoints are public (the judges need to see the dashboard). They expose
  no secrets and no account identifiers.
- The single write endpoint (`/api/kill`) is authenticated.
- Rate limit the API. A public demo URL gets scraped.
- Permissive CORS is acceptable for read-only endpoints; not for the write one.

## Dependencies

- Pin exact versions. Commit the lockfile.
- Run `pip-audit` once before submission and note the result in the README.
- No dependency added after Sep 2 unless it fixes a break.

## What NOT to do for a hackathon

Don't build auth, user accounts, or multi-tenancy. There is one account and one
operator. Complexity that isn't visible to a judge is complexity that costs you
the deadline.
