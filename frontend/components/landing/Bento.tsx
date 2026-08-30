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
import { GateChain } from "@/components/GateChain";
import { Sparkline } from "@/components/Sparkline";
import { StressGrid } from "@/components/StressGrid";
import { TermStructure } from "@/components/TermStructure";
import { VolCone } from "@/components/VolCone";
import { clockTime, regimeColor, timeAgo, volPoints } from "@/lib/format";
import type { Decision, RefusalExhibit, SystemStatus, VolState } from "@/lib/types";

function stateLabel(regime: string): string {
  return regime === "SELL_VOL" ? "vol rich" : regime === "BUY_VOL" ? "vol cheap" : "abstaining";
}

function CellCaption({ children }: { children: React.ReactNode }) {
  return (
    <p className="mono mb-3 text-[10px] uppercase tracking-widest text-[color:var(--text-dim)]">
      {children}
    </p>
  );
}

interface Props {
  states: VolState[];
  counts?: Record<string, number>;
  latest?: Decision;
  exhibit?: RefusalExhibit;
  status?: SystemStatus;
  closed: boolean;
}

export function Bento({ states, counts, latest, exhibit, status, closed }: Props) {
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
  const traced = Object.values(counts ?? {}).reduce(
    (a, b) => a + (typeof b === "number" ? b : 0),
    0,
  );

  return (
    <div ref={gridRef} className="grid grid-cols-2 gap-3 md:grid-cols-12">
      {/* THE PREMIUM RIGHT NOW — spans half the top row */}
      <div className="bento-cell panel col-span-2 p-5 md:col-span-6">
        <CellCaption>the premium, right now</CellCaption>
        {byGap.length === 0 ? (
          <p className="text-sm text-[color:var(--text-dim)]">
            The desk is not reachable from here — nothing on this page is
            invented in its absence.
          </p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4">
              {byGap.slice(0, 8).map((state) => (
                <div key={state.symbol}>
                  <p className="mono text-[10px] text-[color:var(--text-dim)]">{state.symbol}</p>
                  <CountUp
                    value={state.vrp}
                    format={(v) => volPoints(v)}
                    className="font-display block text-[1.7rem] leading-tight"
                    style={{ color: regimeColor(state.regime) }}
                  />
                  <p className="mono mb-1 text-[9px] uppercase tracking-wider text-[color:var(--text-dim)]">
                    {stateLabel(state.regime)}
                  </p>
                  <Sparkline slices={state.skew_slices} color={regimeColor(state.regime)} />
                </div>
              ))}
            </div>
            <p className="mono mt-4 text-[9px] text-[color:var(--text-dim)]">
              {closed && hero
                ? `as of ${clockTime(hero.as_of)} · last session`
                : "reading live from the desk"}
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
        <p className="mono mt-3 text-[10px] leading-relaxed text-[color:var(--text-dim)]">
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
        <ul className="mono mt-3 space-y-1 text-[10px] leading-relaxed text-[color:var(--text-dim)]">
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
          <p className="text-xs text-[color:var(--text-dim)]">cone pending first scan</p>
        )}
      </div>

      {/* TERM STRUCTURE */}
      <div className="bento-cell panel col-span-1 p-5 md:col-span-3">
        <CellCaption>term structure {hero ? `· ${hero.symbol}` : ""}</CellCaption>
        {hero && hero.term_curve.length >= 2 ? (
          <TermStructure points={hero.term_curve} slope={hero.term_slope} />
        ) : (
          <p className="text-xs text-[color:var(--text-dim)]">term curve pending first scan</p>
        )}
      </div>

      {/* LAST DECISION — live proof, links to the full trace */}
      <div className="bento-cell panel col-span-2 p-5 md:col-span-6">
        <CellCaption>last decision</CellCaption>
        {latest ? (
          <Link href={`/trace/${latest.id}`} className="group block">
            <p className="mono text-[10px] text-[color:var(--text-dim)]">
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
              <span className="mono text-[11px] uppercase tracking-wider">
                {latest.action.toLowerCase()}
              </span>
              {latest.symbol && (
                <span className="mono text-[11px] text-[color:var(--text-dim)]">
                  {latest.symbol}
                </span>
              )}
            </p>
            <p className="mt-2 line-clamp-3 text-[12px] leading-relaxed text-[color:var(--text)]">
              {latest.reason}
            </p>
            <p className="mono mt-3 text-[10px] uppercase tracking-wider text-[color:var(--text-dim)] group-hover:text-[color:var(--brass)]">
              open the full decision trace →
            </p>
          </Link>
        ) : (
          <p className="text-sm text-[color:var(--text-dim)]">
            No decision recorded yet — the log fills with the first cycle.
          </p>
        )}
      </div>

      {/* STRESS GRID — a real refusal, compact */}
      <div className="bento-cell panel col-span-2 p-5 md:col-span-6">
        <CellCaption>the stress engine · a real refusal</CellCaption>
        {exhibit?.available && exhibit.cells ? (
          <StressGrid cells={exhibit.cells} maxLoss={exhibit.max_loss ?? 1} refused />
        ) : (
          <p className="text-sm text-[color:var(--text-dim)]">
            No breach recorded yet — this cell fills with the first real one,
            never a mock.
          </p>
        )}
      </div>

      {/* GATE CHAIN */}
      <div className="bento-cell panel col-span-2 p-5 md:col-span-6">
        <CellCaption>deterministic gates · bounded selector</CellCaption>
        <GateChain />
        <p className="mt-4 max-w-xl text-[13px] leading-relaxed text-[color:var(--text)]">
          The model can choose among approved structures. It cannot invent one.
        </p>
      </div>

      {/* status line cell */}
      <div className="bento-cell panel col-span-2 p-5 md:col-span-6">
        <CellCaption>the desk, now</CellCaption>
        <ul className="mono space-y-1.5 text-[11px] leading-relaxed">
          <li>
            <span className="text-[color:var(--text-dim)]">market</span>{" "}
            {status ? (status.market_open ? "open" : "closed") : "—"}
          </li>
          <li>
            <span className="text-[color:var(--text-dim)]">universe</span>{" "}
            {status?.universe_size ?? "—"} names
          </li>
          <li>
            <span className="text-[color:var(--text-dim)]">last cycle</span>{" "}
            {status?.last_cycle ? timeAgo(status.last_cycle) : "—"}
          </li>
          <li>
            <span className="text-[color:var(--text-dim)]">account</span>{" "}
            {status?.account_id_suffix ? `…${status.account_id_suffix} (paper)` : "paper"}
          </li>
        </ul>
      </div>
    </div>
  );
}
