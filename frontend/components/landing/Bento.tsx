"use client";

/**
 * The bento — section two, the centrepiece. Twelve columns of REAL
 * instruments: every cell reads live from the API and degrades to a static
 * readout when JS or motion is unavailable. No decorative cards.
 *
 * Reveal: one staggered pass, 60ms per cell, opacity + 12px rise, driven by
 * ScrollTrigger and run ONCE. Initial hidden states are set by GSAP at
 * runtime, so a no-JS reader sees every cell immediately.
 */

import Link from "next/link";
import { useEffect, useRef } from "react";

import { CountUp } from "@/components/CountUp";
import { Sparkline } from "@/components/Sparkline";
import { TermStructure } from "@/components/TermStructure";
import { VolCone } from "@/components/VolCone";
import { clockTime, dollars, regimeColor, timeAgo, volPoints } from "@/lib/format";
import type { Decision, RiskAuthority, VolState } from "@/lib/types";

/** The desk's MCP surface — the real tool names from skew/mcp_server.py.
 *  Static by nature: the tool list is code, not market data. */
const MCP_TOOLS: Array<{ name: string; blurb: string }> = [
  { name: "scan_volatility", blurb: "vol state for the universe" },
  { name: "propose_structures", blurb: "defined-risk candidates" },
  { name: "stress_test", blurb: "the 84-scenario grid" },
  { name: "risk_status", blurb: "tier, budgets, headroom" },
  { name: "positions", blurb: "open book, marked" },
  { name: "audit_log", blurb: "every decision, with reasons" },
  { name: "desk_status", blurb: "armed, market, account" },
  { name: "execute", blurb: "gated, confirm-required" },
  { name: "close", blurb: "gated, confirm-required" },
];

function stateLabel(regime: string): string {
  return regime === "SELL_VOL" ? "vol rich" : regime === "BUY_VOL" ? "vol cheap" : "abstaining";
}

function CellCaption({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-4 text-[13px] font-semibold uppercase tracking-[0.12em] text-[color:var(--text-dim)]">
      {children}
    </p>
  );
}

interface Props {
  states: VolState[];
  counts?: Record<string, number>;
  latest?: Decision;
  risk?: RiskAuthority;
  closed: boolean;
  /** "reading live from the desk" / "as of 14:43 · last known" / "recorded 30 Aug". */
  provenance?: string | null;
}

export function Bento({ states, counts, latest, risk, closed, provenance }: Props) {
  const gridRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const grid = gridRef.current;
    if (!grid || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let killed = false;
    let teardown: (() => void) | undefined;
    void (async () => {
      const [{ gsap }, { ScrollTrigger }] = await Promise.all([
        import("gsap"),
        import("gsap/ScrollTrigger"),
      ]);
      if (killed) return;
      gsap.registerPlugin(ScrollTrigger);
      const cells = grid.querySelectorAll(".bento-cell");
      const tween = gsap.fromTo(
        cells,
        { opacity: 0, y: 12 },
        {
          opacity: 1,
          y: 0,
          duration: 0.5,
          ease: "power2.out",
          stagger: 0.06,
          scrollTrigger: { trigger: grid, start: "top 78%", once: true },
        },
      );
      teardown = () => tween.scrollTrigger?.kill();
    })();
    return () => {
      killed = true;
      teardown?.();
    };
  }, []);

  const byGap = [...states].sort((a, b) => Math.abs(b.vrp) - Math.abs(a.vrp));
  const hero = byGap[0];
  const traced =
    counts?.TOTAL ??
    Object.entries(counts ?? {})
      .filter(([k]) => k !== "TOTAL")
      .reduce((a, [, v]) => a + (typeof v === "number" ? v : 0), 0);

  return (
    <div ref={gridRef} className="grid grid-cols-2 gap-3 md:grid-cols-12">
      {/* THE PREMIUM RIGHT NOW — spans half the top row */}
      <div className="bento-cell panel col-span-2 p-5 md:col-span-6">
        <CellCaption>the premium, right now</CellCaption>
        {byGap.length === 0 ? (
          <p className="text-sm text-[color:var(--text-dim)]">
            Loading the recorded state — one beat, never a blank.
          </p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4">
              {byGap.slice(0, 8).map((state) => (
                <div key={state.symbol}>
                  <p className="mono text-[12px] text-[color:var(--text-dim)]">{state.symbol}</p>
                  <CountUp
                    value={state.vrp}
                    format={(v) => volPoints(v)}
                    className="font-display block text-[1.7rem] leading-tight"
                    style={{ color: regimeColor(state.regime) }}
                  />
                  <p className="mono mb-1 text-[12px] uppercase tracking-wider text-[color:var(--text-dim)]">
                    {stateLabel(state.regime)}
                  </p>
                  <Sparkline slices={state.skew_slices} color={regimeColor(state.regime)} />
                </div>
              ))}
            </div>
            <p className="mono mt-4 text-[12px] text-[color:var(--text-dim)]">
              {provenance ??
                (closed && hero ? `as of ${clockTime(hero.as_of)} · last session` : "")}
            </p>
          </>
        )}
      </div>

      {/* DECISION COUNTER */}
      <div className="bento-cell panel col-span-1 p-5 md:col-span-3">
        <CellCaption>decisions traced</CellCaption>
        <CountUp
          value={traced}
          format={(v) => Math.round(v).toLocaleString("en-US")}
          className="font-display block text-[3rem] leading-none"
        />
        <p className="mono mt-3 text-[12px] leading-relaxed text-[color:var(--text-dim)]">
          {(counts?.REFUSED ?? 0).toLocaleString("en-US")} refused ·{" "}
          {(counts?.EXECUTED ?? 0).toLocaleString("en-US")} executed — every one
          replayable to its inputs
        </p>
      </div>

      {/* PAPER ONLY */}
      <div className="bento-cell panel col-span-1 p-5 md:col-span-3">
        <CellCaption>paper only</CellCaption>
        <p className="font-display text-[1.4rem] leading-tight">
          No live code path exists.
        </p>
        <ul className="mono mt-3 space-y-1 text-[12px] leading-relaxed text-[color:var(--text-dim)]">
          <li>base url pinned to the paper endpoint</li>
          <li>startup refuses anything else</li>
          <li>defined-risk structures only</li>
        </ul>
      </div>

      {/* VOL CONE */}
      <div className="bento-cell panel col-span-1 p-5 md:col-span-3">
        <CellCaption>
          realized-vol cone {hero ? `· ${hero.symbol}` : ""}
        </CellCaption>
        {hero && hero.vol_cone.length >= 2 ? (
          <VolCone
            cone={hero.vol_cone}
            ivAtm={hero.iv_atm}
            ivDte={hero.skew_slices[0]?.dte ?? 30}
          />
        ) : (
          <p className="text-xs text-[color:var(--text-dim)]">loading…</p>
        )}
      </div>

      {/* TERM STRUCTURE */}
      <div className="bento-cell panel col-span-1 p-5 md:col-span-3">
        <CellCaption>term structure {hero ? `· ${hero.symbol}` : ""}</CellCaption>
        {hero && hero.term_curve.length >= 2 ? (
          <TermStructure points={hero.term_curve} slope={hero.term_slope} />
        ) : (
          <p className="text-xs text-[color:var(--text-dim)]">loading…</p>
        )}
      </div>

      {/* LAST DECISION — live proof, links to the full trace */}
      <div className="bento-cell panel col-span-2 p-5 md:col-span-6">
        <CellCaption>last decision</CellCaption>
        {latest ? (
          <Link href={`/trace/${latest.id}`} className="group block">
            <p className="mono text-[12px] text-[color:var(--text-dim)]">
              {clockTime(latest.ts)} · {timeAgo(latest.ts)}
            </p>
            <p className="mt-1 flex items-baseline gap-2">
              <span
                className="inline-block h-[7px] w-[7px] shrink-0"
                style={{
                  background:
                    latest.action === "EXECUTED"
                      ? "var(--verdigris)"
                      : latest.action === "REFUSED"
                        ? "var(--oxide)"
                        : "var(--line)",
                  borderRadius: "1px",
                }}
                aria-hidden
              />
              <span className="mono text-[13px] uppercase tracking-wider">
                {latest.action.toLowerCase()}
              </span>
              {latest.symbol && (
                <span className="mono text-[13px] text-[color:var(--text-dim)]">
                  {latest.symbol}
                </span>
              )}
            </p>
            <p className="mt-2 line-clamp-3 text-[14px] leading-relaxed text-[color:var(--text)]">
              {latest.reason}
            </p>
            <p className="mono mt-3 text-[12px] uppercase tracking-wider text-[color:var(--text-dim)] group-hover:text-[color:var(--brass)]">
              open the full decision trace →
            </p>
          </Link>
        ) : (
          <p className="text-sm text-[color:var(--text-dim)]">
            No decision recorded yet — the log fills with the first cycle.
          </p>
        )}
      </div>

      {/* RISK AUTHORITY — the earned-permission model, live or recorded */}
      <div className="bento-cell panel col-span-2 p-5 md:col-span-6">
        <CellCaption>risk authority</CellCaption>
        {risk ? (
          <div className="flex flex-wrap items-end justify-between gap-6">
            <div>
              <p className="font-display text-[2.6rem] leading-none">Tier {risk.tier}</p>
              <p className="mono mt-2 text-[12px] uppercase tracking-wider text-[color:var(--text-dim)]">
                {(risk.max_loss_pct * 100).toFixed(1)}% per trade · earned, never configured
              </p>
            </div>
            <ul className="mono space-y-1.5 text-[13px]">
              <li>
                <span className="text-[color:var(--text-dim)]">per trade&nbsp;&nbsp;</span>
                {dollars(risk.budget_dollars)}
              </li>
              <li>
                <span className="text-[color:var(--text-dim)]">portfolio&nbsp;&nbsp;</span>
                {dollars(risk.used_dollars)} / {dollars(risk.portfolio_cap_dollars)}
              </li>
              <li>
                <span className="text-[color:var(--text-dim)]">positions&nbsp;&nbsp;</span>
                {risk.open_positions} / {risk.max_concurrent_positions}
              </li>
              <li>
                <span className="text-[color:var(--text-dim)]">breaches&nbsp;&nbsp;&nbsp;</span>
                {risk.breaches}
              </li>
            </ul>
          </div>
        ) : (
          <p className="text-xs text-[color:var(--text-dim)]">loading…</p>
        )}
        <p className="mono mt-4 text-[12px] leading-relaxed text-[color:var(--text-dim)]">
          Budgets grow only with clean closed trades; a drawdown demotes the
          tier automatically. There is no setting to raise them.
        </p>
      </div>

      {/* MCP SURFACE — the desk as tools for any MCP client */}
      <div className="bento-cell panel col-span-2 p-5 md:col-span-6">
        <CellCaption>mcp surface · the desk as tools</CellCaption>
        <ul className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
          {MCP_TOOLS.map((tool) => (
            <li key={tool.name} className="mono flex items-baseline gap-2 text-[13px]">
              <span className="text-[color:var(--text)]">{tool.name}</span>
              <span className="truncate text-[12px] text-[color:var(--text-dim)]">
                {tool.blurb}
              </span>
            </li>
          ))}
        </ul>
        <p className="mono mt-4 text-[12px] leading-relaxed text-[color:var(--text-dim)]">
          Every read is open; the two mutating tools run the same gate chain and
          require explicit confirmation. Claude connects to this desk the same
          way you do.
        </p>
      </div>

    </div>
  );
}
