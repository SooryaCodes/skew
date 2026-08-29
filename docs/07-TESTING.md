# 07 — Testing

AEGIS-Q's submission explicitly advertises 20 passing tests and CI. Judges notice.
More importantly, the vol math has to be right — a finance judge will check it, and
wrong math is worse than no math.

## What must be tested

### Non-negotiable — the maths

- **Max loss** for every structure type, against hand-worked examples. A put credit
  spread with strikes 580/575 and $0.80 credit has a max loss of $420. Assert it.
- **Realized volatility** against a known series with a known answer. Get the
  annualisation factor right — √252, not √365.
- **Black-Scholes repricing** against published reference values. Off-by-one on
  time-to-expiry in years is the classic bug.
- **Ratio quantity GCD** — a 2:4 spread must be normalised to 1:2 or Alpaca rejects it.
- **Credit/debit sign convention** on mleg limit prices.

### Non-negotiable — the gates

- Each gate independently, pass and fail, with a synthetic candidate.
- Backwardation must **always** block a premium-selling structure. This is the
  gate that keeps the system honest; test it hard.
- Stress gate must fail when any cell breaches, and the returned `detail` must
  identify the correct cell.
- Budget gate must respect the current tier.

### Non-negotiable — the bounded agent

- Model returns a candidate ID not in the provided list → treated as ABSTAIN, logged
- Model returns malformed JSON → treated as ABSTAIN, logged
- Model attempts to return a modified structure → rejected
- Empty candidate list → ABSTAIN without calling the model

### Worth testing if time allows

- Loop skips outside market hours
- Kill switch halts entries but not monitoring
- Idempotency: same client_order_id doesn't double-submit
- Risk tier promotion and demotion transitions

## How

- `pytest`, no network in unit tests. Fixture the Alpaca responses from real
  captured JSON — save a real chain response to `tests/fixtures/` on day one.
- One integration test that hits the paper API and places a real 2-leg order,
  marked `@pytest.mark.integration` and excluded from CI.
- GitHub Actions: ruff + pytest on push. Cheap to set up, visible in the repo, and
  a green badge in the README is a credibility signal for thirty seconds of work.

## Target

Around 25–30 meaningful tests. Not coverage theatre — every test should map to a
way the system could be wrong about money.
