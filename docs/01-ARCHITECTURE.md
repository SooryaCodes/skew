# 01 — Architecture

## 1. Module map

```
backend/
├── skew/
│   ├── config.py            settings, env loading, paper-only assertion
│   ├── data/
│   │   ├── chains.py        option chain + snapshot fetch (IV & Greeks come free)
│   │   ├── bars.py          underlying OHLCV history
│   │   ├── calendar.py      market hours, expirations, earnings dates
│   │   └── store.py         snapshot persistence for the IV history builder
│   ├── vol/
│   │   ├── realized.py      close-to-close, Parkinson, Garman-Klass
│   │   ├── implied.py       ATM IV extraction, surface slice by strike
│   │   ├── term.py          term structure slope: contango vs backwardation
│   │   ├── rank.py          IV rank / percentile (see §4 — read before building)
│   │   └── vrp.py           the core signal
│   ├── structures/
│   │   ├── base.py          Structure model: legs, max_loss, breakevens, greeks
│   │   ├── credit.py        put credit spread, call credit spread, iron condor
│   │   ├── debit.py         call debit spread, put debit spread
│   │   └── selection.py     strike selection by delta target
│   ├── gates/
│   │   ├── base.py          GateResult, the chain runner
│   │   ├── liquidity.py
│   │   ├── earnings.py
│   │   ├── term_structure.py
│   │   ├── stress.py
│   │   └── budget.py
│   ├── stress/
│   │   ├── scenarios.py     the shock grid
│   │   └── reprice.py       Black-Scholes repricing under each scenario
│   ├── agent/
│   │   ├── bounded.py       the constrained selector
│   │   └── prompt.py        system prompt + candidate serialisation
│   ├── exec/
│   │   ├── submit.py        atomic mleg order construction
│   │   ├── monitor.py       profit target, loss limit, DTE, deadline
│   │   └── exit.py
│   ├── risk/
│   │   └── authority.py     earned risk tier state machine
│   ├── audit/
│   │   ├── models.py        SQLAlchemy tables
│   │   └── log.py           append-only decision log
│   ├── loop.py              the scheduler: the core cycle
│   ├── api.py               FastAPI app the frontend reads
│   └── mcp_server.py        FastMCP tool surface
└── tests/

frontend/                    Next.js app — see docs/03-DESIGN-SYSTEM.md
```

## 2. The core loop

Runs every `LOOP_INTERVAL_SECONDS` during market hours.

```
for symbol in universe:
    bars      = fetch_bars(symbol, lookback=90d)
    chain     = fetch_chain(symbol)              # includes IV + greeks
    rv        = realized_vol(bars, window=20)
    iv_atm    = atm_implied_vol(chain)
    vrp       = iv_atm - rv
    term      = term_structure_slope(chain)
    regime    = classify(vrp, term, iv_rank)

    if regime == ABSTAIN: log_and_continue()

    candidates = build_structures(chain, regime)   # 2-3, fully specified
    for c in candidates:
        c.gate_results = run_gates(c)              # liquidity → earnings → term
                                                   #   → stress → budget
    survivors = [c for c in candidates if c.passed_all]

    log_all_gate_results()                         # refusals are the product

    if not survivors: continue

    choice = bounded_agent.select(survivors)       # or ABSTAIN
    if choice is ABSTAIN: log_and_continue()

    order = submit_mleg(choice)
    audit.record(order)

monitor_open_positions()
```

## 3. TRAP — Alpaca gives you IV and Greeks. Do not compute them.

The option chain and snapshot endpoints return implied volatility **and** delta,
gamma, theta, vega per contract.

```python
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionChainRequest

client = OptionHistoricalDataClient(key, secret)
chain = client.get_option_chain(OptionChainRequest(underlying_symbol="SPY"))
# chain["SPY250919C00580000"].implied_volatility
# chain["SPY250919C00580000"].greeks.delta
```

Do not implement Black-Scholes inversion to get IV — you'd be reimplementing a
solved problem and introducing error. Two caveats:

- Greeks are only on **snapshot** endpoints and are computationally expensive.
  Cache aggressively; one chain fetch per symbol per loop, not per candidate.
- You **do** need Black-Scholes for the stress engine (§5), because there you're
  repricing a hypothetical, not reading a market quote.

## 4. TRAP — historical implied volatility does not exist in this API

IV rank is conventionally "where is today's IV within its 52-week range". Alpaca
does not serve historical IV. There is no endpoint. You cannot compute a real
252-day IV rank, and any code that claims to is lying.

Three options, in order of honesty:

**A. Make VRP the primary signal, not IV rank.** VRP = current IV − trailing
realized vol. Both are available right now with zero history. This is the design
decision — the whole strategy is built on VRP for exactly this reason.

**B. Build IV history from today forward.** Run a lightweight poller from the
moment you start that writes ATM IV per symbol to disk every few minutes. By
Sep 3 you'll have four or five days. That's enough to show the mechanism working
and to render a real chart. Label it honestly in the UI as a short window — do not
dress five days up as a year.

**C. Use realized-vol percentile as a regime proxy.** Realized vol history *is*
computable from bars over any lookback. Rank today's realized vol within its own
252-day distribution. This is a legitimate, disclosable substitute.

**Build A as the signal, B for the chart, C as the regime filter.** Say all of
this out loud in the video — a judge who knows the data landscape will respect
that you knew the limitation and designed around it. Pretending otherwise is the
fastest way to lose credibility with the one person you're trying to impress.

## 5. The stress engine

For each candidate, reprice the exact structure across a grid:

- **Price shocks:** −3σ, −2σ, −1σ, 0, +1σ, +2σ, +3σ where σ = 20-day realized vol
  scaled to days-to-expiry
- **IV shocks:** −30%, unchanged, +50%, +100% applied to each leg's IV
- **Time:** now, halfway to expiry, at expiry

7 × 4 × 3 = 84 repriced outcomes per candidate. Reprice each leg with
Black-Scholes under the shocked inputs, net the legs, compare against the position's
entry cost.

The gate fails if worst-case loss in any cell exceeds the current risk budget. The
failing cell's coordinates go into `GateResult.detail` so the UI can highlight it.

This grid is the visual centrepiece of the product and the moment the demo turns.

## 6. The earned risk authority

| Tier | Max loss per trade | Promotion condition | Demotion |
|---|---|---|---|
| 0 | 0.5% of equity | default | — |
| 1 | 1.0% | 3 closed trades, no gate breach | any breach |
| 2 | 2.0% | 6 closed trades, drawdown < 3% | breach or drawdown > 3% |

State persists in the audit database. Surfaced prominently in the UI. The narrative
— an agent that earns the right to size up — is what a brokerage actually wants
from autonomous agents on its API, and no competitor has it.

## 7. Execution contract

Alpaca specifics that will bite you:

```python
MarketOrderRequest(
    qty=1,
    order_class=OrderClass.MLEG,
    time_in_force=TimeInForce.DAY,
    legs=[
        OptionLegRequest(symbol=short_leg, side=OrderSide.SELL,
                         position_intent=PositionIntent.SELL_TO_OPEN, ratio_qty=1),
        OptionLegRequest(symbol=long_leg,  side=OrderSide.BUY,
                         position_intent=PositionIntent.BUY_TO_OPEN,  ratio_qty=1),
    ],
)
```

- Between 2 and 4 legs for options. Iron condor is exactly 4.
- `ratio_qty` values across legs must have **GCD of 1**. A 2:4 ratio is rejected;
  send 1:2.
- `position_intent` is required on each leg for `mleg`.
- For limit orders on `mleg`: **positive limit price = debit, negative = credit.**
  Inverting this sign inverts the trade.
- Always set a unique `client_order_id` for idempotency.

## 8. Data flow to the frontend

FastAPI exposes read-only JSON. The frontend never talks to Alpaca directly and
never holds a key.

```
GET  /api/universe        vol state per symbol
GET  /api/candidates      current candidates with full gate results
GET  /api/stress/{id}     the 84-cell grid for one candidate
GET  /api/positions       open positions
GET  /api/risk            tier, budget, drawdown
GET  /api/audit?limit=n   decision stream
POST /api/kill            kill switch (auth required)
```
