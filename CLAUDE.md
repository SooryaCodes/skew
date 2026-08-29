# Project context for Claude Code

## What this is

SKEW — an autonomous options volatility desk built on Alpaca's paper trading API.

**Core thesis:** the agent never predicts price direction. It measures the spread
between implied volatility and realized volatility (the variance risk premium),
and takes defined-risk options positions based on whether volatility is rich or
cheap. Direction is not an input.

This distinction is the entire product. If you ever find yourself writing code
that forecasts price, stop — that is a different project and a worse one.

## Non-negotiable invariants

1. **Paper only.** The system must refuse to start if the Alpaca base URL is not
   the paper endpoint. There is no live-trading code path, not even behind a flag.
2. **Defined risk only.** Every position has a known, computed maximum loss before
   submission. No naked short options, ever.
3. **Deterministic code decides what is possible; the model only selects.** The LLM
   receives fully-specified, pre-validated candidates and may pick one or abstain.
   It cannot invent contracts, change strikes, alter quantities, or bypass a gate.
   Never pass raw account access or an execution function to the model.
4. **Atomic multi-leg.** Spreads are submitted as a single `mleg` order class
   order. Never leg in with separate orders.
5. **Every decision is logged.** Gate results, model rationale, orders, fills and
   exits all land in the audit log with timestamps. Refusals are logged as
   prominently as executions — they are the product's best feature.
6. **No P&L in the headline.** Performance over a few days is noise. The interface
   and the pitch lead with risk architecture, not returns.

## Style

- Python: 3.11+, type hints everywhere, Pydantic v2 for all cross-module shapes.
- Prefer pure functions for anything in `vol/`, `structures/`, `stress/`. They must
  be testable without network access.
- Every gate returns `GateResult(passed: bool, reason: str, detail: dict)`. The
  reason string is user-facing and appears in the UI — write it for a human.
- No bare `except`. No silent failures. If market data is missing, abstain loudly.
- Frontend: TypeScript strict mode. No `any`.

## Working agreement

- Work one phase at a time. Stop at the end of each phase and summarise what was
  built and what you'd flag before I review.
- Commit at each checkpoint marked in the phase prompt, using the format in
  `docs/08-GIT-WORKFLOW.md`.
- If a spec in `docs/` is wrong or impossible, say so rather than working around it
  silently. The spec was written before the code existed and may be wrong.
- If you need a credential, a decision, or an account setting from me, ask
  explicitly and stop. Do not stub it and continue.

## Known traps

- **Alpaca provides IV and Greeks in the option chain/snapshot endpoints.** Do not
  implement Black-Scholes inversion for IV. Read `docs/01-ARCHITECTURE.md` §3.
- **Alpaca does not provide historical implied volatility.** IV rank over a long
  lookback is therefore not computable from the API. See `docs/01-ARCHITECTURE.md`
  §4 for the designed workaround. This has killed naive versions of this project.
- **Multi-leg ratio quantities must be in simplest form** — the GCD across legs
  must be 1, or Alpaca rejects the order.
- **For `mleg` limit orders, a positive limit price is a debit and a negative
  limit price is a credit.** Getting this sign wrong inverts the trade.
- Greeks are only on snapshot endpoints and are expensive. Cache them.
