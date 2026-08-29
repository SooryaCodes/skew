# SKEW — Autonomous Volatility Desk

An options agent that never predicts price direction. It measures the gap between
implied and realized volatility, and executes defined-risk options structures into
that gap — with every trade gated by a deterministic stress test before the model
is allowed to act.

Built for the Alpaca AI Trading Agents Hackathon. Paper trading only.

---

## How to use this package

This is a build kit, not a codebase. It contains the full specification, a
sequential prompt series for Claude Code, and the hackathon context.

**Order of operations:**

1. Read `YOUR-ACTION-ITEMS.md` first. Some items have lead time (Options Level 3
   approval) and block everything downstream. Do them before you write code.
2. Read `docs/04-OPTIONS-PRIMER.md`. You need roughly forty minutes of options
   literacy to make good calls during the build. It's written for someone who has
   never traded.
3. Copy this whole folder into a fresh git repo.
4. Open Claude Code in that repo. Paste `prompts/PHASE-00-bootstrap.md`.
5. Work through the phases in order. Each ends with a review gate and a commit.
   Do not skip ahead — later phases assume the data contracts from earlier ones.

**Directory map:**

```
CLAUDE.md              Persistent context. Claude Code reads this automatically.
YOUR-ACTION-ITEMS.md   What only you can do. Start here.
.env.example           Copy to .env and fill in.
.gitignore             Ignores hackathon/, .env, and build artefacts.

docs/                  The specification. Committed to the repo.
  00-PROJECT-BRIEF     Thesis, scope, what winning looks like.
  01-ARCHITECTURE      Module map, data flow, the core loop.
  02-TECH-STACK        Final stack with version pins and rationale.
  03-DESIGN-SYSTEM     Tokens, type, layout, component rules.
  04-OPTIONS-PRIMER    Options and volatility, for a non-trader.
  05-SECURITY          Secret handling, paper-only enforcement, kill switch.
  06-DATA-CONTRACTS    Pydantic and TypeScript shapes shared across modules.
  07-TESTING           What must be tested and why.
  08-GIT-WORKFLOW      Commit discipline, branch strategy, review gates.

prompts/               Sequential Claude Code prompts. Run in order.
hackathon/             Competitor analysis, timeline, video script. GITIGNORED.
```

`hackathon/` is deliberately excluded from version control. It contains competitive
analysis and submission strategy that has no business being in a public repo the
judges will read.

---

## The one-line pitch

Every other agent in this hackathon guesses where the market goes. Skew doesn't
guess. It prices fear.
