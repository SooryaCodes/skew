# 00 — Project Brief

## The thesis

Options are not a leveraged bet on direction. They are an instrument for trading
**volatility**. The price of an option is dominated by how much movement the market
expects — implied volatility — and that expectation is systematically different
from how much the underlying actually moves — realized volatility.

The gap between them is the **variance risk premium**. It exists because people
pay for protection, and that payment is persistent and documented. It is the
closest thing to a real, explainable edge available to a hackathon project in six
days, and critically it does not require predicting anything.

Skew measures that gap and takes defined-risk positions into it:

- **Implied vol well above realized vol** → the market is overpaying for fear →
  sell premium via a defined-risk credit spread
- **Implied vol at or below realized vol** → movement is cheap → buy premium via a
  debit spread or calendar
- **Neither, or the regime is stressed** → abstain

Direction is never an input. The agent has no opinion on whether the underlying
goes up or down.

## Why this positioning

Every visible competitor in this hackathon does the same thing underneath:
predict price direction, then buy an option pointing that way. AEGIS-Q wraps
excellent deterministic guardrails around a bull-vs-bear guess. AlphaPilot runs
SMA/RSI/MACD into a call purchase. NewsFlow reads headlines. VibeHedge is the only
one doing real Greeks work, and only defensively — it buys protective puts once
drawdown has already hit.

A judge with a finance background reads "AI predicts price" as the amateur
position, because it is. Skew is the only submission where the model is never
asked to do the thing models cannot do.

Secondary advantages: the Volatility track appears unclaimed, and nobody has
touched Alpaca's open-source Skills Library or built a real MCP server except one team.

## Scope

**In scope:**

- Volatility measurement: implied vs realized, term structure, the VRP signal
- Defined-risk structure construction: credit spreads, iron condors, debit spreads
- Deterministic gate chain including a pre-trade stress test
- Bounded model selection with abstention
- Atomic multi-leg execution on Alpaca paper
- Position monitoring and exit
- Full audit trail
- MCP server exposing the desk as tools
- Web dashboard

**Explicitly out of scope:**

- Any price prediction model
- Machine learning of any kind. VibeHedge already owns the deep-learning angle and
  you will not out-build it in five days. Your edge is the framing and the gates.
- Live trading
- Naked short options
- Portfolio optimisation across many names
- Backtesting infrastructure beyond what the stress engine needs

## What winning looks like

A judge watches a three-minute video in which an autonomous agent:

1. Shows implied vol at 68 while realized vol sits at 12, and explains the gap
2. Constructs a defined-risk credit spread with stated maximum loss
3. Stress-tests that exact structure and **refuses it**, naming the failing scenario
4. Constructs a second candidate, passes it, and fills it as one atomic multi-leg order
5. Shows that the agent's position size is a privilege it earned, not a default

Nobody claims a return figure. The whole pitch is: *this is what it looks like when
an autonomous agent is safe enough to trust with capital.*

## Honest risk assessment

The idea is strong. The execution risk is real and worth naming:

- **The vol math must be correct.** A finance judge will check whether IV rank and
  max loss are computed properly. Wrong math here is worse than not attempting it.
- **Five days is tight for a domain you don't know.** Read the options primer
  before you start; don't learn it from the code.
- **The stress engine is the differentiator.** If you fall behind, cut structures,
  cut dashboard polish, cut the universe — never cut the gates.
