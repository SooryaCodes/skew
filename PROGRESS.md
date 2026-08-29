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

**Works:** Live against the real paper account — Options Level 3 confirmed
active, $100k equity, account PA33HVMQGA5O. `python -m skew.cli scan` prints the
whole universe: SPY IV 11.8 / RV 10.4, NVDA IV 32.9 / RV 46.5, AAPL VRP +5.3.
IV and Greeks come off the Alpaca snapshot as the spec promised. Realized vol is
tested against a hand-worked series to 1e-9. Fixtures are real captures (3,898
SPY contracts, ~500 of them with no IV or no bid) so the parsers meet real junk.

**Flagged:** open interest is on the *trading* API, not the snapshot — handled
with a separately-cached join. Per-contract volume is unavailable at loop cost,
so the liquidity gate keys on OI + spread + quote presence.

## Phase 02 — Structures

**Works:** All five structure types build from live chains with
`max_loss + max_profit == width × 100` holding exactly. Strike selection is by
delta target.

**Corrected during the build:** width is now targeted as a fraction of spot
rather than "N strikes out" — SPY lists $1 strikes near the money, so two
strikes gave a $2-wide spread whose credit barely covered the spread crossed to
enter it. And `Structure.width` reported 51 for an iron condor (lowest strike to
highest); only one wing can finish in the money, so it now reports the wing.

## Phase 03 — Gates and stress engine

**Works:** Five gates, every one evaluated even after the first failure.
Black-Scholes verified against the textbook case and cross-checked by put-call
parity. Earned risk tier persists across restarts.

**A CORRECTION TO THE SPEC.** `docs/01-ARCHITECTURE.md` §5 motivates the stress
engine with "you can be down far more than max loss along the way". That is true
of naked positions. It is **false** for the defined-width verticals this desk
trades: the liability is bounded above by `width × e^(−rT)`, strictly below the
width, so the mark-to-market loss can never exceed the terminal max loss.
Verified empirically at every realized vol from 10% to 100% — the worst grid
cell is always the expiry column, at exactly max loss.

Taken at face value that makes the stress gate a restatement of the budget gate.
So it now also applies the check that *is* additive, and asks a different
question of each side:

- **Short premium:** a routine 1σ move must not already reach more than 60% of
  max loss. Two spreads with the same $420 max loss are completely different
  risks if one's short strike is half a sigma out and the other's two and a half.
- **Long premium:** the same test would refuse every debit spread ever built (an
  adverse move takes 80–100% of the premium at *every* vol level — that is the
  structure working). So it measures breakeven distance in sigma instead.

## Phase 04 — Bounded agent and execution

**Works:** Bounded selector with 26 boundary tests — an unknown id, malformed
JSON, a non-string id, an attempt to return a modified structure, and any API
error all become abstentions. An empty candidate list abstains without calling
the model at all. Atomic mleg submission with the pre-flight gate recheck,
idempotent client order ids, exit rules, append-only audit log, APScheduler loop,
and the FastAPI read surface with an authenticated kill switch. A full dry cycle
runs across all 8 symbols on live data.

**Blocked on a credential:** the Anthropic key is identity-linked and returns
400 without an `anthropic-workspace-id` header. Support for it is wired
(`ANTHROPIC_WORKSPACE_ID`); until it is set the selector abstains, which is the
correct fail-safe — the desk does not trade when the selection step is down.

## Phase 05 — MCP server

**Works:** _pending_

## Phase 06 — Dashboard

**Works:** _pending_

## Phase 07 — Hardening

**Works:** _pending_
