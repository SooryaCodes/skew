# SKEW — an autonomous volatility desk

[![ci](https://github.com/USER/skew/actions/workflows/ci.yml/badge.svg)](https://github.com/USER/skew/actions/workflows/ci.yml)

**SKEW never predicts price direction.** It measures the gap between implied and
realized volatility — the variance risk premium — and takes defined-risk options
structures into that gap. Every trade passes a deterministic gate chain,
including an 84-scenario stress test, *before* a language model is allowed to
choose among what survived.

**Paper trading only. There is no live-trading code path in this repository** —
not behind a flag, not behind an environment variable. See
[The paper-only guarantee](#the-paper-only-guarantee).

Built for the Alpaca AI Trading Agents Hackathon.

---

## Why this is different

Most trading agents ask a language model where a stock is going. Models cannot
do that, and neither can anyone else reliably.

SKEW asks a much easier question: **is movement currently overpriced?** Implied
volatility — what the market charges for movement — is persistently higher than
the volatility that subsequently gets realized, because people buy protection
and funds hedge. That gap is documented and structural, not a pattern found in a
backtest, and measuring it requires no forecast at all.

```
VRP  =  implied volatility  −  trailing realized volatility

VRP well above zero   →  movement is overpriced  →  sell defined-risk premium
VRP at or below zero  →  movement is underpriced →  buy defined-risk premium
neither, or regime is stressed  →  abstain
```

Direction is never an input. The regime classifier's signature takes volatility,
term structure and a volatility percentile — there is nowhere to pass a price
forecast, and [a test asserts
that](backend/tests/test_vol_signal.py).

---

## Architecture

```
                   ┌─────────────────────────────────────────┐
   Alpaca ────────▶│  data/    chains, bars, calendar, store │
   (paper)         │           IV + Greeks come off the       │
                   │           snapshot — never inverted      │
                   └────────────────────┬────────────────────┘
                                        ▼
                   ┌─────────────────────────────────────────┐
                   │  vol/     realized · implied · term      │
                   │           rank · VRP + regime            │
                   └────────────────────┬────────────────────┘
                                        ▼
                   ┌─────────────────────────────────────────┐
                   │  structures/  defined-risk only, max     │
                   │               loss computed before the   │
                   │               structure can exist        │
                   └────────────────────┬────────────────────┘
                                        ▼
     ┌───────────────────────────────────────────────────────────────┐
     │  gates/    liquidity → earnings → term → stress → budget      │
     │            every gate runs even after one fails               │
     │            stress/  84 repriced scenarios per candidate       │
     └────────────────────────────┬──────────────────────────────────┘
                                  ▼  only fully-gated candidates
                   ┌─────────────────────────────────────────┐
                   │  agent/   bounded selector — may pick    │
                   │           one, or abstain. Nothing else. │
                   └────────────────────┬────────────────────┘
                                        ▼
                   ┌─────────────────────────────────────────┐
                   │  exec/    re-run every gate, then ONE    │
                   │           atomic mleg order. Never legs  │
                   │           in. audit/  append-only.       │
                   └─────────────────────────────────────────┘
```

Full module map in [docs/01-ARCHITECTURE.md](docs/01-ARCHITECTURE.md).

---

## The three claims this repository makes

### 1. The paper-only guarantee

The base URL is validated at **import time**. A misconfigured deployment cannot
get as far as constructing a broker client:

```python
# backend/skew/config.py
if "paper" not in v.lower():
    raise PaperOnlyViolation("SKEW is paper-only. Refusing to start.")
```

It is checked again immediately before any Alpaca client is built, and the
trading client is constructed with `paper=True` as a literal, not a variable.
Verify it yourself:

```bash
cd backend && ALPACA_BASE_URL=https://api.alpaca.markets python -c "import skew.config"
```

### 2. The model cannot place a trade

The bounded selector is treated as an untrusted component. It receives a
serialised list of **pre-validated** candidates and nothing else — no account
access, no keys, no tools, no execution function. Its reply is validated down to
one of exactly two outcomes: an ID from the list it was given, or abstain.

| The model does this | SKEW does this |
|---|---|
| Names an ID that was not offered | Abstains, logs it as malformed |
| Returns malformed JSON | Abstains, logs it |
| Returns a modified structure, a quantity, an override flag | Ignores everything but the ID |
| Times out, errors, or is unreachable | Abstains — the desk does not trade when the selection step is down |
| Is given an empty candidate list | Abstains **without calling the model at all** |

Its free-text rationale is stored and displayed but **never parsed for
instructions**. There is no string the model can emit that causes anything other
than one of the N+1 outcomes the risk engine already sanctioned. 26 tests defend
this boundary in
[test_agent_boundary.py](backend/tests/test_agent_boundary.py).

### 3. Position size is earned, not configured

| Tier | Max loss per trade | Promotion | Demotion |
|---|---|---|---|
| 0 | 0.5% of equity | default | — |
| 1 | 1.0% | 3 closed trades, no breach | any breach |
| 2 | 2.0% | 6 closed trades, drawdown < 3% | breach, or drawdown > 3% |

A breach demotes to **tier 0**, not one step down, and is not forgiven by later
clean trades — "wait long enough and it stops counting" is not a risk policy.
The tier persists in SQLite, so it survives a restart. A tier that reset on
deploy would be decorative rather than earned.

---

## The stress engine, and an honest correction

`docs/01-ARCHITECTURE.md` §5 motivates the stress engine with "max loss is what
you lose at expiry, but you can be down far more than that along the way".

**That is true of naked positions. It is false for the defined-width verticals
this desk actually trades**, and provably so: a vertical's liability is bounded
above by `width × e^(−rT)`, strictly less than the width itself. The
mark-to-market loss can never exceed the terminal max loss. We verified this
empirically at every realized volatility from 10% to 100% — the worst cell in
the grid is always the expiry column, at exactly max loss.

Taken at face value, that would make the stress gate a redundant restatement of
the budget gate. So it also applies the check that genuinely adds something, and
asks a different question of each side:

- **Short premium** — does a routine 1σ move already reach more than 60% of the
  max loss? Two spreads with an identical $420 max loss are completely different
  risks if one's short strike sits half a sigma out and the other's two and a
  half, and nothing but the grid can tell them apart.
- **Long premium** — how far away is the breakeven, in sigma? The short-premium
  test would refuse every debit spread ever built, because an adverse move takes
  80–100% of a debit spread's premium at *every* volatility level. That is the
  structure working as designed, not a defect.

A real refusal, rendered verbatim in the UI:

> **Strikes are too close to the money.** An ordinary 1σ move — −1σ with IV
> −30%, halfway to expiry — already loses −$234, 99% of the $237 max loss,
> against a 60% limit. The max loss fits the budget; the path to it is too easy.

---

## Running it

```bash
git clone <this repo> && cd skew
cp .env.example .env          # fill in your Alpaca paper keys
```

**Backend**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m skew.cli account    # verifies the account and Options Level 3
uvicorn skew.api:app --reload
```

**Frontend**

```bash
cd frontend
npm install
echo 'NEXT_PUBLIC_API_BASE=http://localhost:8000' > .env.local
npm run dev
```

**The operator CLI** — every phase's verification step:

```bash
python -m skew.cli scan            # the volatility table across the universe
python -m skew.cli candidates SPY  # structures, gates, and the stress grid
python -m skew.cli cycle           # one full loop cycle, dry by default
python -m skew.cli poll            # store one ATM IV sample per symbol
```

**MCP** — drive the desk conversationally from Claude. Setup takes about thirty
seconds: [docs/MCP-SETUP.md](docs/MCP-SETUP.md).

```bash
claude mcp add skew -- /abs/path/backend/.venv/bin/python -m skew.mcp_server
```

Options **Level 3** is required — without it no multi-leg structure can be
submitted. `python -m skew.cli account` reports it.

---

## Tests

```bash
cd backend && pytest
```

**344 tests.** Not coverage theatre — each one maps to a way the system could be
wrong about money.

| Area | What is actually pinned |
|---|---|
| Realized vol | An 11-close series with alternating ±1% log returns, against a hand-computed 16.7332%, to 1e-9. Asserts the annualisation factor is √252 and **not** √365 |
| Black-Scholes | The textbook case (S=100, K=100, T=1, r=5%, σ=20% → call 10.4506, put 5.5735), cross-checked by put-call parity so a symmetric error cannot slip through |
| Structures | Every type against hand-worked arithmetic. The primer's 580/575 put credit spread for $0.80 → max loss $420, max profit $80, breakeven 579.20 |
| Gates | Each independently, pass and fail. Backwardation must block a premium sale at **+30 vol points of VRP** |
| Agent boundary | Every violation in the table above |
| Execution | The mleg credit/debit sign convention, ratio GCD normalisation, idempotent client order IDs |

Chain parsing runs against **real captured Alpaca responses**, junk included — a
live SPY chain carries ~500 contracts with no implied volatility or no bid, and
a parser tested only on clean data is a parser that breaks on day one.

---

## Honest limitations

**Alpaca serves no historical implied volatility.** There is no endpoint. A real
252-day IV rank is not computable from this API, and any project claiming one is
either using another data source or lying. SKEW does three things instead:

1. **VRP is the primary signal**, not IV rank. Current IV minus trailing realized
   vol — both available right now, with zero history required.
2. **IV history is built forward from first run.** A poller writes ATM IV per
   symbol to SQLite every few minutes. Every rank derived from it carries
   `iv_rank_window_days` alongside it, everywhere it goes, so a five-day window
   can never be presented as a fifty-two week one.
3. **Realized-vol percentile is the regime filter.** Bar history *is* available
   over any lookback, so a 252-day realized-vol percentile is legitimate and
   disclosable.

**Alpaca serves no earnings calendar either** — the corporate-actions endpoint
covers dividends and splits. Earnings dates come from an operator-maintained
file, and a single name with no confirmed date is **blocked**, not waved through.
The file distinguishes confirmed dates from estimated ones, and the gate says
which it used rather than claiming more certainty than the data has.

**Open interest is not on the option snapshot.** It lives on `OptionContract` in
the trading API, so the liquidity gate joins a separately-cached fetch. Per-
contract daily volume would need a bars call per contract — too expensive for a
five-minute loop — so liquidity keys on open interest, quote presence and
bid-ask width, and `MIN_VOLUME` defaults to 0.

**No P&L claim is made.** Performance over a few days of paper trading is noise,
and this project deliberately does not lead with it. Positions sit behind a tab
rather than on the landing view. The honest headline is the ratio of refusals to
executions.

**Not investment advice.** Paper trading only, built for a hackathon.

---

## Security

`pip-audit`: **no known vulnerabilities.** Full detail in
[docs/05-SECURITY.md](docs/05-SECURITY.md).

- The Alpaca key never reaches the browser. The only `NEXT_PUBLIC_` variable is
  `NEXT_PUBLIC_API_BASE`, a URL. The built client bundle is scanned for
  credentials as part of the release check.
- Read endpoints are public and expose no secret and no account identifier. The
  single write endpoint, `POST /api/kill`, takes a shared secret compared in
  constant time.
- Every order carries a unique `client_order_id`, so a retry after a network
  timeout cannot double-fill.
- The gate chain is re-run immediately before submission — the market moves while
  the model is thinking.
- MCP write tools are **not registered** unless `MCP_ALLOW_EXECUTE=true`. They
  are absent from the tool list rather than refused at call time, so an
  accidental connection has nothing to attempt.

---

## Repository

```
backend/skew/     the desk — 49 modules
  config.py       the paper-only assertion
  models.py       every cross-module contract
  data/           Alpaca access, all through one seam
  vol/            the signal
  structures/     defined-risk construction
  gates/          the five deterministic checks
  stress/         Black-Scholes and the 84-cell grid
  agent/          the bounded selector
  exec/           atomic submission, monitoring, exits
  risk/           the earned tier state machine
  audit/          append-only decision log
  loop.py         the cycle · api.py · mcp_server.py · cli.py
backend/tests/    344 tests, real captured fixtures
frontend/         Next.js 15, TypeScript strict, Tailwind v4
docs/             the specification
```

`hackathon/` and `prompts/` are gitignored — build scaffolding, not product.

---

*Nothing here is investment advice. Paper trading only; there is no live-trading
code path, by design.*
