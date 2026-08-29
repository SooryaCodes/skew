# Connecting SKEW to Claude

SKEW exposes the desk as an MCP server, so you can drive it conversationally:
scan for mispriced volatility, propose structures, read the stress grid, check
the risk tier. Setup is about thirty seconds.

**Read tools are always available. Write tools are not registered at all unless
you explicitly enable them** — see [Enabling execution](#enabling-execution).

---

## Prerequisites

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env      # then fill in your Alpaca paper keys
```

Confirm the account first. This also verifies Options Level 3, without which no
multi-leg structure can be submitted:

```bash
python -m skew.cli account
```

---

## Claude Code

```bash
claude mcp add skew -- /absolute/path/to/backend/.venv/bin/python -m skew.mcp_server
```

Then `/mcp` in a session to confirm it connected.

## Claude Desktop

Edit the config file:

- macOS — `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows — `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "skew": {
      "command": "/absolute/path/to/skew/backend/.venv/bin/python",
      "args": ["-m", "skew.mcp_server"],
      "cwd": "/absolute/path/to/skew/backend"
    }
  }
}
```

Restart Claude Desktop. SKEW appears in the tools menu.

**Both paths need absolute paths**, and the `command` must be the Python inside
the virtualenv — not a bare `python`, which will not have `alpaca-py` installed.

Credentials are read from `.env`; you never put a key in the MCP config.

---

## The tools

| Tool | What it does |
|---|---|
| `desk_status` | Configuration and safety posture. A good first call. |
| `scan_volatility` | Implied vs realized vol across the universe, with the regime and the reasoning |
| `propose_structures` | Defined-risk candidates for one symbol, with every gate result |
| `stress_test` | The 84-scenario grid behind one candidate |
| `risk_status` | Earned tier, budget, drawdown, and what it takes to size up |
| `positions` | Open positions with live mark-to-market P&L |
| `audit_log` | The append-only decision stream |
| `execute` | Submit a candidate. **Off by default.** |
| `close` | Close a position. **Off by default.** |

---

## A session that shows what the desk actually does

> **Scan the universe and tell me where volatility is mispriced.**

Returns implied vs realized per symbol. Each state carries an `explanation`
written for a human — worth quoting rather than paraphrasing, because it names
the exact threshold that was hit.

> **Propose structures for AAPL.**

Two or three fully-specified candidates with real contract symbols, a computed
maximum loss, and all five gates evaluated.

> **Why was that one refused?**

The gate chain evaluates **every** gate even after one fails, so you get the
whole picture rather than the first thing that went wrong. Reason strings carry
real numbers:

> *Strikes are too close to the money. An ordinary 1σ move — −1σ with IV −30%,
> halfway to expiry — already loses −$234, 99% of the $237 max loss, against a
> 60% limit. The max loss fits the budget; the path to it is too easy.*

> **Show me the stress grid for the one that passed.**

All 84 cells. Note `routine_move` in the response — see below for why it is the
number that matters.

> **What risk tier is the desk on, and what would it take to size up?**

---

## Two things worth knowing when reading the output

**A vertical's worst case is always its max loss.** For a defined-width spread
the liability is bounded above by `width × e^(−rT)`, so no scenario in the grid
can exceed the terminal max loss — the worst cell always lands in the expiry
column. This corrects `docs/01-ARCHITECTURE.md` §5, which motivates the engine
with "you can be down far more than that along the way"; that holds for naked
positions, not for these.

So the grid's real work is the `routine_move` measurement: **how much of the max
loss an ordinary 1σ move already reaches.** Two spreads with an identical $420
max loss are completely different risks if one's short strike sits half a sigma
away and the other's two and a half, and nothing but the grid can tell them
apart. For long-premium structures the question inverts — the gate measures
breakeven distance in sigma instead, because an adverse move takes 80–100% of a
debit spread's premium at every volatility level and that is the structure
working as designed.

**IV rank is not a 52-week rank.** Alpaca serves no historical implied
volatility — there is no endpoint. SKEW builds its own history forward from
first run, and every rank is returned with `iv_rank_window_days` attached so it
can never be presented as something longer than it is.

---

## Enabling execution

`execute` and `close` are **not registered** unless enabled. They are absent
from the tool list, not merely refused, so an accidental connection sees a
read-only server and there is nothing for a model to try.

```bash
MCP_ALLOW_EXECUTE=true python -m skew.mcp_server
```

Or set `MCP_ALLOW_EXECUTE=true` in `.env`. `desk_status` reports which mode you
are in.

Even enabled, the surface is not a bypass around the risk engine:

- **The full gate chain is re-run before submission.** A candidate id from
  earlier in the conversation is not a permission slip; the market moved while
  you were talking. If the structure no longer passes, `execute` refuses and
  names the failing gate.
- **The candidate is re-derived from a fresh chain**, not read from a stale
  snapshot. Only a structure the desk would build *right now* can be submitted.
- **`confirm=true` is required**, so a model cannot trade in one unconsidered
  call.
- **Paper only.** The base URL is asserted at import and again before any client
  is constructed. There is no live-trading code path anywhere in this codebase.

---

## Troubleshooting

**Server does not appear.** The `command` must be the venv's Python, by absolute
path. Test it in isolation:

```bash
cd backend && .venv/bin/python -m skew.mcp_server
```

It should start and wait on stdin. Ctrl-C to exit.

**Tools return an empty scan.** Credentials are missing or wrong. Run
`python -m skew.cli account` — it will say so plainly.

**`propose_structures` returns no candidates.** Usually correct behaviour, not a
fault. Check `abstain_reason`: volatility is often fairly priced, and the desk
declining to trade is the normal case.

**`stress_test` cannot find a candidate id.** Ids live for the session. Call
`propose_structures` again.

**`execute` is missing.** By design. See above.
