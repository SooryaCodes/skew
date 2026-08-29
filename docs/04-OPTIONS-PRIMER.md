# 04 — Options and Volatility, for someone who has never traded

Read this before you build. Forty minutes here will save you two days of building
the wrong thing, and it's the difference between defending your project in a
judging call and freezing.

---

## 1. What an option is

A **call** gives you the right to buy 100 shares at a fixed price (the **strike**)
before a fixed date (the **expiration**). A **put** gives you the right to sell at
the strike.

You pay a **premium** for that right. If you never use it, the premium is gone.

- Buying an option: limited loss (the premium), large potential gain
- Selling an option: you collect the premium, and you take on the obligation.
  Selling alone can lose far more than you collected — this is why **we never sell
  a naked option**.

One contract covers 100 shares. A quoted price of $1.20 costs $120.

## 2. Reading a contract symbol

```
SPY   250919 P 00580000
│     │      │ │
│     │      │ └── strike × 1000 → $580.00
│     │      └──── P = put, C = call
│     └─────────── expires 2025-09-19
└───────────────── underlying
```

You'll see these constantly. Always render them in mono, uppercase.

## 3. The part that matters: volatility

An option's price is driven by how much the market **expects** the underlying to
move before expiry. More expected movement means a more valuable option, in both
directions — a call and a put both get more expensive when expected movement rises.

That expectation, backed out of the option's market price, is **implied volatility
(IV)**. It's quoted as an annualised percentage. IV of 20% means the market expects
roughly a 20% annualised range of movement.

**Realized volatility (RV)** is how much the underlying *actually* moved, computed
from historical prices. Also annualised, so the two are directly comparable.

### The variance risk premium

Here's the whole thesis in one line:

> **IV is usually higher than the RV that follows.**

People buy protection. Funds hedge. That demand persistently pushes IV above what
subsequently gets realized. The gap — `VRP = IV − RV` — is a documented, structural
feature of options markets, not a pattern someone found in a backtest.

When VRP is large and positive, options are expensive relative to actual movement,
so **selling** premium has an edge. When VRP is near zero or negative, options are
cheap, so **buying** has an edge.

**Notice what's missing: any opinion about direction.** That's the point. Every
other team in this hackathon is asking a language model to guess whether a stock
goes up. We're asking a much easier question: is movement currently overpriced?

## 4. The Greeks, briefly

Sensitivities of an option's price. Alpaca gives you all of these in the chain, so
you don't compute them — you just need to know what they mean.

| Greek | Meaning | Why we care |
|---|---|---|
| **Delta** | Price change per $1 move in the underlying | We select strikes by delta. Delta ≈ rough probability of finishing in-the-money |
| **Gamma** | How fast delta changes | High gamma near expiry is why short-dated short options are dangerous |
| **Theta** | Value lost per day of time passing | When we sell premium, theta is what we're collecting |
| **Vega** | Price change per 1 point of IV | This is our real exposure. We're trading vega, not delta |

If you take one thing: **we are a vega business.** Direction is noise we neutralise;
volatility is the thing we have a view on.

## 5. The structures we build

All defined-risk. Every one has a computable maximum loss before we place it.

### Put credit spread — our bread and butter when vol is rich

Sell a put at a lower strike, buy a further-out put as protection.

```
SELL  SPY 580 put   collect $2.00
BUY   SPY 575 put   pay     $1.20
                    ───────────────
net credit          $0.80  →  $80 collected
```

- **Max profit:** the $80 credit, if SPY stays above 580
- **Max loss:** (580 − 575) × 100 − 80 = **$420**
- Bought put caps the loss. This is why it's defined risk.
- Profits if SPY goes up, sideways, *or* drifts down slightly. Direction-tolerant.

### Call credit spread

Mirror image — sell a call, buy a higher one. Use when we want the short side.

### Iron condor — both at once

A put credit spread *and* a call credit spread on the same underlying. Collects
premium from both sides, profits if the underlying stays in a range. Four legs.
Maximum expression of "vol is overpriced and I don't care which way it goes."

### Debit spreads — when vol is cheap

Buy the nearer option, sell the further one to reduce cost. Pay a debit; that debit
is the max loss.

## 6. Term structure: contango and backwardation

Plot IV against expiration date.

- **Contango** — further-out options have higher IV. This is normal. Calm market.
- **Backwardation** — near-term IV is higher than long-dated. The market is scared
  *right now*.

**This is a hard gate in our system: never sell premium in backwardation.** Selling
volatility into a panic is the single most reliable way to blow up an options
account. Every real vol trader knows this, and a judge with a finance background
will look for it. Having this gate is a credibility signal all by itself.

## 7. Why the stress test matters

Max loss is what you lose if you hold to expiry. But you can be down far more than
that *along the way*, and margin can force you out at the worst moment.

The stress grid asks: what is this position worth if the underlying gaps 2σ against
us **and** implied vol doubles, halfway to expiry? That's a real Monday morning,
not a hypothetical.

If the answer breaches our budget, we don't take the trade — even though the
theoretical max loss looked fine. That gap between "max loss at expiry" and
"worst case along the way" is exactly what unsophisticated systems miss, and it's
what our whole differentiator is built on.

## 8. Vocabulary for the video

Use these correctly and you'll sound like you know the domain:

- **premium** — the option's price
- **rich / cheap** — expensive or inexpensive relative to fair value
- **defined risk** — maximum loss known in advance
- **legging in** — placing spread legs separately (bad, we don't)
- **DTE** — days to expiration
- **ATM / OTM** — at-the-money, out-of-the-money
- **assignment** — being forced to honour a short option
- **IV crush** — implied vol collapsing after an event like earnings

## 9. What not to say

- Don't claim an edge you haven't measured. Say "the variance risk premium is a
  documented structural feature", not "our strategy makes money".
- Don't quote returns from a few days of paper trading.
- Don't call it "AI-powered trading". It's a volatility desk with a bounded model
  in the selection step. That precision is what makes it credible.

---

*This primer is background for building the hackathon project. It isn't investment
advice, and nothing here should inform decisions with real money.*
