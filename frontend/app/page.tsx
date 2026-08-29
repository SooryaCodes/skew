"use client";

/**
 * The desk.
 *
 * Three columns, mirroring the actual decision sequence: **scan, decide,
 * govern.** Positions and P&L live on a second screen behind a tab — a
 * deliberate, defensible choice. The product's claim is that risk governance
 * matters more than returns, and the layout should say that before any words do.
 */

import { useEffect, useMemo, useState } from "react";

import { AuditStream } from "@/components/AuditStream";
import { CandidateCard } from "@/components/CandidateCard";
import { Header } from "@/components/Header";
import { RiskPanel } from "@/components/RiskPanel";
import { UniverseRail } from "@/components/UniverseRail";
import { VolReadout } from "@/components/VolReadout";
import {
  useAudit,
  useAuditCounts,
  useCandidates,
  useRisk,
  useStatus,
  useUniverse,
} from "@/lib/api";
import { volPoints } from "@/lib/format";

export default function DeskPage() {
  const { data: status } = useStatus();
  const { data: universe, isLoading: universeLoading, error: universeError } = useUniverse();
  const { data: candidates } = useCandidates();
  const { data: risk } = useRisk();
  const { data: audit } = useAudit(40);
  const { data: counts } = useAuditCounts();

  const [selected, setSelected] = useState<string | null>(null);

  const states = useMemo(() => universe ?? [], [universe]);

  // Focus the richest-volatility name by default — that is where the desk is
  // most likely to have something to say.
  useEffect(() => {
    if (selected === null && states.length > 0) {
      const richest = [...states].sort((a, b) => b.vrp - a.vrp)[0];
      if (richest) setSelected(richest.symbol);
    }
  }, [states, selected]);

  const focused = states.find((s) => s.symbol === selected);
  const focusedCandidates = useMemo(
    () => (candidates ?? []).filter((c) => c.structure.symbol === selected),
    [candidates, selected],
  );

  const abstainCopy = useMemo(() => {
    if (!states.length) return null;
    const below = states.filter((s) => s.regime === "ABSTAIN").length;
    if (below === states.length) {
      return `No candidates — every one of the ${states.length} names is inside the VRP band or otherwise standing down.`;
    }
    return null;
  }, [states]);

  return (
    <div className="flex min-h-screen flex-col">
      <Header status={status} tab="desk" />

      <div className="grid flex-1 grid-cols-1 lg:grid-cols-[13rem_minmax(0,1fr)_19rem]">
        {/* scan */}
        <aside className="border-b border-[color:var(--line)] lg:border-b-0 lg:border-r">
          <UniverseRail
            states={states}
            selected={selected}
            onSelect={setSelected}
            loading={universeLoading}
          />
        </aside>

        {/* decide */}
        <main className="min-w-0 p-4">
          {universeError ? (
            <p className="text-sm text-[color:var(--text-dim)]">
              Cannot reach the desk API. Start the backend with{" "}
              <span className="mono">uvicorn skew.api:app</span> and check{" "}
              <span className="mono">NEXT_PUBLIC_API_BASE</span>.
            </p>
          ) : !focused ? (
            <p className="text-sm text-[color:var(--text-dim)]">
              {universeLoading
                ? "Scanning — the first cycle takes a few seconds."
                : "Select a symbol to see its volatility state."}
            </p>
          ) : (
            <>
              <VolReadout state={focused} />

              <section className="mt-6" aria-label="Candidates">
                <div className="mb-3 flex items-baseline justify-between">
                  <h2 className="mono text-[10px] uppercase tracking-widest text-[color:var(--text-dim)]">
                    candidates
                  </h2>
                  {focusedCandidates.length > 0 && (
                    <span className="mono text-[10px] text-[color:var(--text-dim)]">
                      {focusedCandidates.filter((c) => c.passed_all).length} of{" "}
                      {focusedCandidates.length} survived the gate chain
                    </span>
                  )}
                </div>

                {focusedCandidates.length === 0 ? (
                  // Empty states are instructions, not "No data".
                  <p className="text-sm text-[color:var(--text-dim)]">
                    {abstainCopy ??
                      `No candidates for ${focused.symbol} — ${focused.note}`}
                  </p>
                ) : (
                  <div className="grid gap-4 xl:grid-cols-2">
                    {focusedCandidates.map((candidate) => (
                      <CandidateCard key={candidate.structure.id} candidate={candidate} />
                    ))}
                  </div>
                )}
              </section>
            </>
          )}
        </main>

        {/* govern */}
        <aside className="flex max-h-screen flex-col border-t border-[color:var(--line)] lg:border-l lg:border-t-0">
          <RiskPanel risk={risk} />
          <div className="min-h-0 flex-1 border-t border-[color:var(--line)]">
            <AuditStream decisions={audit ?? []} counts={counts} />
          </div>
        </aside>
      </div>

      <footer className="border-t border-[color:var(--line)] px-4 py-2">
        <p className="mono text-[10px] text-[color:var(--text-dim)]">
          {states.length > 0 && (
            <>
              {states.length} names scanned · widest VRP{" "}
              {volPoints(Math.max(...states.map((s) => s.vrp)))} ·{" "}
            </>
          )}
          paper trading only · no live code path exists · direction is never an input
        </p>
      </footer>
    </div>
  );
}
