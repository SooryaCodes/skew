/**
 * /mcp — the desk as tools, for judges to try.
 *
 * Static by design: this page documents code, not market state, so it needs no
 * data spine. Same system, both themes, readable without JavaScript.
 */

import Link from "next/link";

import { Nav } from "@/components/landing/Nav";

export const metadata = {
  title: "SKEW — MCP server",
  description: "Drive the volatility desk conversationally: the SKEW MCP server, its tools, and thirty-second setup for Claude Desktop and Claude Code.",
};

const READ_TOOLS: Array<{ sig: string; blurb: string }> = [
  { sig: "scan_volatility(symbols?)", blurb: "Volatility state for the universe — IV, RV, VRP, regime per name." },
  { sig: "propose_structures(symbol)", blurb: "Defined-risk candidates for one name, sized to the risk budget." },
  { sig: "stress_test(candidate_id)", blurb: "The 84-scenario grid for a candidate: price × IV × time, breaches marked." },
  { sig: "risk_status()", blurb: "Tier, per-trade and portfolio budgets, headroom, drawdown." },
  { sig: "positions()", blurb: "The open book, marked to market, with exit conditions." },
  { sig: "audit_log(limit?, action?)", blurb: "Every decision with its reason — refusals as prominent as fills." },
  { sig: "desk_status()", blurb: "Armed state, market clock, account (paper), last cycle." },
];

const WRITE_TOOLS: Array<{ sig: string; blurb: string }> = [
  { sig: "execute(candidate_id, confirm)", blurb: "Submit one gated candidate as an atomic multi-leg order. Requires confirm=true and runs the full gate chain again first." },
  { sig: "close(position_id, confirm)", blurb: "Close one open structure as a single order. Same confirmation contract." },
];

function Code({ children }: { children: string }) {
  return (
    <pre className="panel overflow-x-auto p-5 text-[13px] leading-relaxed">
      <code className="mono">{children}</code>
    </pre>
  );
}

export default function McpPage() {
  return (
    <div className="relative min-h-screen">
      <Nav />
      <main className="mx-auto w-full max-w-3xl px-6 pb-32 pt-36">
        <h1 className="font-display text-[2.6rem] leading-tight sm:text-[3.2rem]">
          The desk as tools
        </h1>
        <p className="mt-6 text-[17px] leading-[1.7] text-[color:var(--text-dim)]">
          SKEW ships a Model Context Protocol server, so any MCP client — Claude
          Desktop, Claude Code — can drive the desk conversationally: scan for
          mispriced volatility, read a stress grid, inspect the risk tier,
          replay any decision. Reads are always available.{" "}
          <strong className="font-semibold text-[color:var(--text)]">
            The two mutating tools are not even registered unless explicitly
            enabled
          </strong>
          , and both re-run the full gate chain and require an explicit
          confirmation argument. The model gets a desk, never a blank cheque.
        </p>

        <h2 className="mt-16 text-[15px] font-semibold uppercase tracking-[0.14em] text-[color:var(--text-dim)]">
          Read tools — always on
        </h2>
        <ul className="mt-5 space-y-4">
          {READ_TOOLS.map((tool) => (
            <li key={tool.sig}>
              <p className="mono text-[14px] text-[color:var(--text)]">{tool.sig}</p>
              <p className="mt-0.5 text-[14px] text-[color:var(--text-dim)]">{tool.blurb}</p>
            </li>
          ))}
        </ul>

        <h2 className="mt-12 text-[15px] font-semibold uppercase tracking-[0.14em] text-[color:var(--text-dim)]">
          Write tools — off unless enabled, confirm-required
        </h2>
        <ul className="mt-5 space-y-4">
          {WRITE_TOOLS.map((tool) => (
            <li key={tool.sig}>
              <p className="mono text-[14px] text-[color:var(--text)]">{tool.sig}</p>
              <p className="mt-0.5 text-[14px] text-[color:var(--text-dim)]">{tool.blurb}</p>
            </li>
          ))}
        </ul>

        <h2 className="mt-16 text-[15px] font-semibold uppercase tracking-[0.14em] text-[color:var(--text-dim)]">
          Claude Code — one line
        </h2>
        <div className="mt-4">
          <Code>{`claude mcp add skew -- /absolute/path/to/skew/backend/.venv/bin/python -m skew.mcp_server`}</Code>
        </div>
        <p className="mt-3 text-[14px] text-[color:var(--text-dim)]">
          Then <span className="mono">/mcp</span> inside a session to confirm it
          connected.
        </p>

        <h2 className="mt-12 text-[15px] font-semibold uppercase tracking-[0.14em] text-[color:var(--text-dim)]">
          Claude Desktop
        </h2>
        <p className="mt-3 text-[14px] text-[color:var(--text-dim)]">
          macOS:{" "}
          <span className="mono text-[13px]">
            ~/Library/Application Support/Claude/claude_desktop_config.json
          </span>{" "}
          · Windows: <span className="mono text-[13px]">%APPDATA%\Claude\claude_desktop_config.json</span>
        </p>
        <div className="mt-4">
          <Code>{`{
  "mcpServers": {
    "skew": {
      "command": "/absolute/path/to/skew/backend/.venv/bin/python",
      "args": ["-m", "skew.mcp_server"],
      "cwd": "/absolute/path/to/skew/backend"
    }
  }
}`}</Code>
        </div>
        <p className="mt-3 text-[14px] text-[color:var(--text-dim)]">
          Absolute paths, and the command must be the virtualenv&rsquo;s Python —
          a bare <span className="mono">python</span> will not have{" "}
          <span className="mono">alpaca-py</span> installed. Restart Claude
          Desktop and SKEW appears in the tools menu.
        </p>

        <h2 className="mt-16 text-[15px] font-semibold uppercase tracking-[0.14em] text-[color:var(--text-dim)]">
          Try this — under a minute
        </h2>
        <ol className="mt-5 list-decimal space-y-3 pl-5 text-[15px] leading-relaxed text-[color:var(--text)]">
          <li>
            <em>&ldquo;What&rsquo;s the desk&rsquo;s status?&rdquo;</em> — armed
            state, market clock, tier, paper-only guarantee.
          </li>
          <li>
            <em>&ldquo;Scan volatility and tell me which name has the widest gap
            between implied and realized.&rdquo;</em> — the live VRP table,
            regime per name.
          </li>
          <li>
            <em>&ldquo;Propose structures for that name and stress-test the
            first one.&rdquo;</em> — real candidates sized to the budget, then
            the 84-cell grid with any breaches marked.
          </li>
          <li>
            <em>&ldquo;Show the last five decisions and why.&rdquo;</em> — the
            audit log, refusals included, each traceable.
          </li>
        </ol>

        <div className="mt-16 flex flex-wrap gap-3">
          <Link
            href="/desk"
            className="btn-3d t-fast bg-[color:var(--accent)] px-6 py-3 text-[15px] font-semibold text-white"
            style={{ borderRadius: "12px" }}
          >
            Enter the desk
          </Link>
          <Link
            href="/"
            className="btn-3d-ghost t-fast border border-[color:var(--line)] bg-[color:var(--panel)] px-6 py-3 text-[15px] font-semibold text-[color:var(--text)]"
            style={{ borderRadius: "12px" }}
          >
            Back to the landing
          </Link>
        </div>
      </main>
    </div>
  );
}
