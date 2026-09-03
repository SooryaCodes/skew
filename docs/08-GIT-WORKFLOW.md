# 08 — Git Workflow

## Branching

`main` only. It's five days with a tiny team; branch overhead buys nothing. If two
people touch the same module, coordinate verbally.

## Commit discipline

Commit at every checkpoint marked in the phase prompts. Roughly 4–8 commits per
phase, 40+ over the project. A repo with one "final commit" the night before
reads badly to anyone who looks.

Format:

```
<area>: <what changed>

<why, if not obvious>
```

Areas: `data`, `vol`, `structures`, `gates`, `stress`, `agent`, `exec`, `risk`,
`audit`, `mcp`, `api`, `ui`, `docs`, `test`, `ci`, `chore`

Examples:

```
vol: add Parkinson realized volatility estimator

Close-to-close underestimates when there's intraday range without
net movement. Parkinson uses high/low and is the better input to VRP.
```

```
gates: block premium selling in backwardation

Inverted term structure means the market is pricing near-term stress.
Selling vol into it is the standard way to blow up an options account.
```

## Rules

- **Never commit `.env`.** Verify `git status` before the first push.
- **Never commit `hackathon/`.** It's gitignored — confirm it's actually ignored
  before pushing, because judges will read this repo.
- Don't commit broken code to `main`. If you must checkpoint mid-refactor, say so
  in the message.
- Tag `v0.1` when the first real order fills. It's a nice artefact for the repo.

## Per-phase checkpoint

At the end of each phase:

1. Run the tests
2. Run ruff
3. Commit
4. Write two lines in `docs/PROGRESS.md`: what works now, what's known broken

`docs/PROGRESS.md` is committed. It's a running build log, and it's genuinely useful
when you're writing the README at 2am on Sep 4.
