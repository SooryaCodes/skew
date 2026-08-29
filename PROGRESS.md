# Build log

Running record of what works and what is known broken. Two lines per phase
checkpoint. Written as we go so the README does not have to be reconstructed
from memory at 2am on Sep 4.

---

## Phase 00 — Bootstrap

**Works:** Backend package skeleton with the full module layout from
`docs/01-ARCHITECTURE.md` §1. `skew/config.py` enforces the paper-only guarantee
at import time and refuses any base URL without "paper" in it. `skew/models.py`
carries every contract from `docs/06-DATA-CONTRACTS.md`, with `max_loss > 0` and
the leg-ratio GCD both enforced in the model rather than left to convention.
Frontend is Next.js 15 / React 19 / Tailwind v4, TypeScript strict with
`noUncheckedIndexedAccess`, design tokens and all three Google faces wired, and a
placeholder page that renders the palette. `npm run build` is clean. CI runs ruff
+ pytest and typecheck + build on push.

**Known broken / flagged:**

- **Open interest is not on the option snapshot.** `docs/01-ARCHITECTURE.md` §3 is
  right that IV and Greeks come free on the chain, but `OptionsSnapshot` carries
  only `symbol / latest_trade / latest_quote / implied_volatility / greeks`. Open
  interest lives on `OptionContract` from the **trading** API
  (`TradingClient.get_option_contracts`), so the liquidity gate needs a second,
  separately-cached fetch joined by contract symbol. Handled in Phase 01.
- **Per-contract daily volume is not on the snapshot either.** It would require a
  `get_option_bars` call per contract, which is too expensive for a 5-minute loop.
  The liquidity gate therefore uses open interest + bid/ask spread + quote
  presence, and `MIN_VOLUME` defaults to 0. Documented rather than faked.
- No credentials present, so nothing has been run against the live paper API yet.

## Phase 01 — Data layer and volatility engine

**Works:** _pending_

## Phase 02 — Structures

**Works:** _pending_

## Phase 03 — Gates and stress engine

**Works:** _pending_

## Phase 04 — Bounded agent and execution

**Works:** _pending_

## Phase 05 — MCP server

**Works:** _pending_

## Phase 06 — Dashboard

**Works:** _pending_

## Phase 07 — Hardening

**Works:** _pending_
