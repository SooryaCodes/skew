# 03 — Design System

You said you don't know trading, so this section explains *why* each choice is
what it is. Every decision below is derived from the subject matter, not from a
template.

## The trap to avoid

Search "trading dashboard UI" and you get one look: pure black background, one
acid-green accent, a wall of tickers, a giant P&L number. It is the default, it is
what the other submissions will produce, and it fights our thesis — we are
deliberately not leading with P&L.

We're building a **desk**, not a dashboard. A desk is a place where a decision gets
made and defended. That framing drives everything below.

## Palette

Two poles, because the product has exactly two states: volatility is expensive, or
volatility is cheap. Colour carries meaning here, it isn't decoration.

```css
--ground:  #0B0E1A;  /* deep indigo-black — not pure black; has a temperature */
--surface: #131829;  /* raised panels */
--line:    #232B45;  /* hairlines, grid, dividers */
--text:    #E6E9F2;  /* primary */
--muted:   #7A85A8;  /* labels, axes, secondary */

--rich:    #E8A33D;  /* amber — vol is EXPENSIVE, sell premium */
--cheap:   #4DA5C4;  /* cool blue — vol is CHEAP, buy premium */
--breach:  #D9534F;  /* a gate FAILED — nothing else, ever */
```

Amber for expensive vol is a nod to phosphor trading terminals, and it reads as
"heat" — the market is hot, fear is priced in. Cool blue reads as calm. Anyone
looking at the screen understands the temperature before they read a number.

**The rule that makes the demo work:** `--breach` red appears **nowhere** in the
interface except a failed gate. Not for losses, not for down days, not for sell
orders. It is the only red on the screen, so when a stress cell breaches during
the video, the eye goes straight to it. Spend that colour once.

## Typography

Three roles, three faces. All free on Google Fonts.

| Role | Face | Use |
|---|---|---|
| Display | **Archivo**, 600–700, tight tracking (−0.02em) | Section headers, the symbol under focus, the title card |
| Body | **Instrument Sans**, 400–500 | Prose, gate reasons, model rationale |
| Data | **IBM Plex Mono**, 400–500, `font-variant-numeric: tabular-nums` | Every number, every contract symbol, the audit log |

Why not Inter — it's the default on every AI-generated interface and carries no
point of view. Why IBM Plex Mono over JetBrains Mono — Plex has a slightly more
institutional, less startup feel, which suits a risk-authority product, and its
tabular figures are clean.

**Tabular numerals are non-negotiable** on anything numeric. Prices that jitter
horizontally as digits change look amateur instantly to anyone who has used a real
trading tool.

Type scale: `12 / 14 / 16 / 20 / 28 / 40 / 64`. Contract symbols always mono,
always uppercase, never wrapped.

## Layout

Three columns, mirroring the actual decision sequence — scan, decide, govern.

```
┌──────────────────────────────────────────────────────────────────────┐
│  SKEW          live skew curve (ambient, always moving)    TIER 1 ▮▮▯ │
├────────────┬─────────────────────────────────────┬───────────────────┤
│ UNIVERSE   │  SPY                                │  RISK AUTHORITY   │
│            │  ─────────────────────────────      │                   │
│ SPY  +14.2 │  IV 24.1   RV 9.9   VRP +14.2       │  Tier 1           │
│ QQQ  +9.7  │                                     │  Budget  1.0%     │
│ IWM  +2.1  │  [ skew curve across strikes ]      │  Used    0.4%     │
│ AAPL -1.4  │                                     │  Drawdown 0.8%    │
│ NVDA +18.9 │  CANDIDATES                         │                   │
│            │  ┌───────────────────────────────┐  │  AUDIT            │
│            │  │ Put credit spread  580/575    │  │  ───────          │
│            │  │ max loss $420   credit $80    │  │  14:32 REFUSED    │
│            │  │ [ payoff curve ]              │  │   stress −2σ/+100%│
│            │  │ [ stress grid 7×4 ]           │  │  14:27 passed     │
│            │  │ liquidity ✓ earnings ✓        │  │  14:22 abstained  │
│            │  │ term ✓ stress ✗ budget —      │  │   VRP below floor │
│            │  └───────────────────────────────┘  │                   │
└────────────┴─────────────────────────────────────┴───────────────────┘
```

Positions and P&L live on a **second screen**, reached by a tab. This is a
deliberate, defensible choice: the product's claim is that risk governance matters
more than returns, and the layout should say that before any words do.

## The signature element

**The skew curve as the header's spine.**

Implied volatility plotted across strike prices forms a curve — lower strikes carry
higher IV because people pay up for downside protection. That asymmetry is called
the skew, and it is literally the product's name.

Render it live in the header, thin stroke, ambient, redrawing as data updates. It
is not a chart in a panel; it is the identity of the application. A visitor sees
the thesis before reading a word.

Secondary signature: **the stress grid**. 7 columns (price shocks) × 4 rows (IV
shocks), each cell a small square shaded by outcome. Almost always calm. When one
cell breaches, it goes `--breach` and the entire candidate card desaturates to 40%
opacity. That single transition is the money shot of the demo video.

## Motion

One orchestrated moment, not scattered effects.

- The skew curve redraws with a 400ms ease when data updates. Ambient, subtle.
- **The refusal:** breaching cell fades to `--breach` over 200ms, then the candidate
  card desaturates over 300ms, then the audit log entry slides in. A 700ms
  sequence, choreographed. This is the only animation with any drama in it.
- Everything else: 120ms opacity transitions. Nothing bounces. Nothing pulses.

Respect `prefers-reduced-motion` — skip the desaturation, keep the colour change.

## Component rules

- **Panels:** `--surface` on `--ground`, 1px `--line` border, 2px radius. Nearly
  square corners; this is an instrument, not a consumer app.
- **No shadows.** Depth comes from the border and background step. Shadows read as
  web-app, not terminal.
- **Gate results:** a row per gate with the name, a state glyph (`✓ ✗ —`) and the
  reason string in body face. The reason is written for a human and it appears in
  the UI verbatim — so write it well in the backend.
- **Numbers:** always mono, always tabular, always with an explicit sign on
  anything that can be negative.
- **Empty states are instructions.** "No candidates — VRP below entry floor on all
  8 names" not "No data".

## Quality floor

Responsive to 768px (judges may watch on a laptop). Visible keyboard focus rings.
Contrast at least 4.5:1 for body text — `--muted` on `--ground` passes, don't go
dimmer. No text baked into images.

## Copy voice

Terse, precise, never salesy. The interface talks like a risk system:

- "Refused — worst case −$1,240 at −2σ with IV +100%, exceeds tier budget $1,000"
- not "Oops! This trade looks a bit risky 😬"

Errors state what happened and what to do. Refusals state the exact failing
condition with numbers. That precision *is* the product's personality.
