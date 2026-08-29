# 02 — Tech Stack

Chosen for five days of build time, not for a production trading desk. Where a
more sophisticated option existed, it was rejected if it cost setup time that
wasn't visible to a judge.

## Backend — Python

| Layer | Choice | Why |
|---|---|---|
| Runtime | Python 3.11+ | `alpaca-py` is the reference SDK and options examples are all Python |
| API | FastAPI | Async, typed, OpenAPI for free |
| Server | Uvicorn | Standard |
| Broker SDK | `alpaca-py` | First-party. Options chain, Greeks, and `mleg` orders all supported |
| Models | Pydantic v2 | Every cross-module shape. Also gives you JSON serialisation for the API and MCP for free |
| Math | NumPy, SciPy, pandas | Realized vol, Black-Scholes repricing, the scenario grid |
| Options pricing | `py_vollib` (or a hand-rolled BS in ~40 lines) | Only needed for the stress engine. Hand-rolling is fine and removes a dependency |
| Scheduler | APScheduler | In-process, no broker needed |
| Storage | SQLite via SQLAlchemy 2.x | Audit log and risk-tier state. Zero infra. Swap to Postgres only if you deploy multi-instance |
| MCP | FastMCP | Python-native MCP server |
| LLM | Anthropic SDK, Claude Sonnet | The bounded selector. Also on-brand: Alpaca markets its MCP server with Claude |
| Tests | pytest, pytest-asyncio | |
| Lint | Ruff | One tool for lint + format |

**Deliberately rejected:** Celery/Redis (overkill for one loop), any ML framework
(off-thesis and unbeatable in the time), Postgres for v1 (setup cost, no visible
benefit), a separate backtesting engine (stress grid covers the demo need).

## Frontend

| Layer | Choice | Why |
|---|---|---|
| Framework | Next.js 15, App Router | Vercel deploy in one command |
| Language | TypeScript, strict | |
| Styling | Tailwind CSS v4 | Token-driven, matches the design system in `03` |
| Charts | Recharts | Payoff curves, vol time series. Sufficient and fast to write |
| Heatmap | Hand-rolled SVG or CSS grid | The stress grid is 7×4 — a chart library is more friction than help |
| Data | SWR with a 5s refresh | Live feel without websocket complexity |
| Fonts | Archivo, Instrument Sans, IBM Plex Mono | See `03` |

**Deliberately rejected:** websockets (polling is enough at a 5-minute loop and
saves half a day), a component library (shadcn would make it look like every other
submission — the design system is a differentiator here), D3 (Recharts covers it).

## Infrastructure

| Concern | Choice |
|---|---|
| Frontend host | Vercel |
| Backend host | Railway or Render, Docker | 
| Why not serverless | The loop needs a persistent process |
| Secrets | Platform env vars. Never in the repo, never in the client bundle |
| Repo | GitHub, public |

## Version pinning

Pin exact versions in `requirements.txt` and commit the lockfile. A dependency
bumping mid-hackathon and breaking the build at 2am on Sep 3 is a real and stupid
way to lose.

## Structure

Monorepo, two roots:

```
/backend    Python service + MCP server
/frontend   Next.js app
/docs       this specification
/prompts    the build sequence
```

Deploy independently. The frontend reads `NEXT_PUBLIC_API_BASE`.
