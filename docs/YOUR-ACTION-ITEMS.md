# What only you can do

Claude Code cannot create accounts, approve permissions, or hold credentials.
These are yours. The first three are blocking — nothing downstream works without them.

---

## Blocking — do tonight

### 1. Alpaca paper account, dedicated to this project

The hackathon requires a **new, dedicated paper trading account**. Don't reuse a
personal one; the judges may check the account's trade history and you want it clean.

- Sign up at alpaca.markets, create a paper account
- Fund it to **$100,000** (paper balance — configurable in the dashboard)
- Record the API key and secret into `.env`

### 2. Options Level 3 — request immediately

**This is the single biggest risk to the timeline.** Level 3 is what permits
multi-leg spreads. Without it every structure in this project is unbuildable and
you'd be left submitting single-leg directional trades, which is the exact thing
we're trying not to be.

Approval is not always instant. Request it the moment the account exists, and
check back within a few hours. If it stalls past Aug 31, tell me — the fallback
plan is different enough that we'd need to restructure.

### 3. Verify a multi-leg order by hand

Before writing any code, place one spread manually through the Alpaca dashboard
or a curl request. Two legs, same underlying, same expiry, different strikes.

If this fills, Level 3 is genuinely active and the whole plan is viable. If it
errors, you've found the problem on day one instead of day four.

---

## Also needed

### 4. Anthropic API key

For the bounded selector model. Console at console.anthropic.com. Into `.env`.

### 5. lablab team registration

Register the team on the hackathon page. Do it early — you'll want the submission
draft posted by Sep 1 and you can't post without a team.

### 6. Deploy targets

- **Vercel** account for the frontend
- **Railway** or **Render** for the Python backend (needs to run a persistent loop,
  so serverless won't work)
- **GitHub** repo, public — judges will read it

### 7. Team split

If Edwin and Farhan are in, the clean division is:

- **You:** frontend, design system, deploy, video. This is your lane and the
  dashboard is a genuine differentiator.
- **Person 2:** `vol/` and `structures/` — the math. Needs to be careful work.
- **Person 3:** `gates/`, `stress/`, `exec/` — the risk layer.

If you're solo, cut the universe to SPY and QQQ only and drop the calendar spread.

---

## Decisions I need from you as we go

Claude Code will stop and ask when it hits these. Deciding them now saves time:

| Decision | Default if you don't care |
|---|---|
| Universe size | SPY, QQQ, IWM + 5 liquid large caps |
| Loop interval | 5 minutes during market hours |
| Max concurrent positions | 3 |
| Starting risk tier | Tier 0 — 0.5% max loss per trade |
| Backend host | Railway |

---

## Things you must never do

- Commit `.env`, or paste keys into a prompt, a screenshot, or the demo video.
  **Check the video frames before uploading** — an exposed key in a screen recording
  is the classic hackathon disaster.
- Point this at a live account. There is no live code path by design; don't add one.
- Show the `hackathon/` folder contents in the repo or the video.
