"use client";

/**
 * The desk.
 *
 * Three columns, mirroring the actual decision sequence: **scan, decide,
 * govern.** The centre column keeps every computation and shows one thing at a
 * time: hero dials, the three instruments, ONE candidate at full depth, the
 * rest as single lines that promote on click. Density of computation, not
 * density of simultaneous display.
 */

import { useEffect, useMemo, useState } from "react";

import { AuditStream } from "@/components/AuditStream";
import { CandidateCard } from "@/components/CandidateCard";
import { CandidateTabs, panelId } from "@/components/CandidateTabs";
import { ControlStrip } from "@/components/ControlStrip";
import { Header } from "@/components/Header";
import { RiskPanel } from "@/components/RiskPanel";
import { KillBanner, SessionStrip } from "@/components/SessionStrip";
import { SkewCurve } from "@/components/SkewCurve";
import { TermStructure } from "@/components/TermStructure";
import { UniverseRail } from "@/components/UniverseRail";
import { VolCone } from "@/components/VolCone";
import { VolReadout } from "@/components/VolReadout";
import { VRPHistory } from "@/components/VRPHistory";
import {
  useAudit,
  useAuditCounts,
  useCandidates,
  useRisk,
  useStatus,
  useUniverse,
} from "@/lib/api";
import { clockTime } from "@/lib/format";
import { captureOperatorToken, isOperator } from "@/lib/operator";

function Instrument({ caption, children }: { caption: string; children: React.ReactNode }) {
  return (
    <div className="panel p-3">
      <p className="mono mb-2 text-[10px] uppercase tracking-widest text-[color:var(--text-dim)]">
        {caption}
      </p>
      {children}
    </div>
  );
}

export default function DeskPage() {
  const { data: status } = useStatus();
  const { data: universe, isLoading: universeLoading, error: universeError } = useUniverse();
  const { data: candidates } = useCandidates();
  const { data: risk } = useRisk();
  const { data: audit } = useAudit(60);
  const { data: counts } = useAuditCounts();

  const [selected, setSelected] = useState<string | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);

  // Token capture happens once, client-side, and the URL is scrubbed. The
  // operator flag only flips after mount so SSR and hydration agree.
  const [operator, setOperator] = useState(false);
  useEffect(() => {
    captureOperatorToken();
    setOperator(isOperator());
  }, []);

  const states = useMemo(() => universe ?? [], [universe]);

  // DEFAULT SELECTION is a separate concern from rail sorting. The rail sorts
  // by |VRP|; the default opens on the most ACTIONABLE symbol — the widest-gap
  // name with surviving candidates, else with any candidates, else the widest
  // gap. NVDA topping the rail while abstaining with zero candidates used to
  // open the desk on an empty state.
  useEffect(() => {
    if (selected !== null || states.length === 0 || candidates === undefined) return;
    const byGap = [...states].sort((a, b) => Math.abs(b.vrp) - Math.abs(a.vrp));
    const has = (symbol: string, survivorsOnly: boolean) =>
      candidates.some(
        (c) => c.structure.symbol === symbol && (!survivorsOnly || c.passed_all),
      );
    const pick =
      byGap.find((s) => has(s.symbol, true)) ??
      byGap.find((s) => has(s.symbol, false)) ??
      byGap[0];
    if (pick) setSelected(pick.symbol);
  }, [states, candidates, selected]);

  const focused = states.find((s) => s.symbol === selected);
  const focusedCandidates = useMemo(
    () => (candidates ?? []).filter((c) => c.structure.symbol === selected),
    [candidates, selected],
  );

  // One candidate holds the stage; a new symbol resets the choice.
  useEffect(() => {
    setFocusId(null);
  }, [selected]);

  const stagedCandidate = useMemo(() => {
    if (focusedCandidates.length === 0) return null;
    return (
      focusedCandidates.find((c) => c.structure.id === focusId) ??
      focusedCandidates.find((c) => c.passed_all) ??
      focusedCandidates[0] ??
      null
    );
  }, [focusedCandidates, focusId]);

  return (
    // The desk shell is a fixed-height flex column at lg+: header rows fixed,
    // body flex-1 with MIN-HEIGHT 0 (without it a flex child refuses to shrink
    // and its children overflow the page), three columns each scrolling
    // independently. The page itself never scrolls; the footer never leaves.
    <div className="flex min-h-screen flex-col lg:h-[100dvh] lg:min-h-0 lg:overflow-hidden">
      <Header status={status} tab="desk" />
      <KillBanner />
      {operator && <ControlStrip />}
      <SessionStrip />

      <div className="grid flex-1 grid-cols-1 lg:min-h-0 lg:grid-cols-[13rem_minmax(0,1fr)_19rem] lg:grid-rows-[minmax(0,1fr)]">
        {/* scan */}
        <aside className="border-b border-[color:var(--line)] lg:overflow-y-auto lg:border-b-0 lg:border-r">
          <UniverseRail
            states={states}
            selected={selected}
            onSelect={setSelected}
            loading={universeLoading}
          />
        </aside>

        {/* decide */}
        <main className="min-w-0 p-4 lg:overflow-y-auto">
          {universeError ? (
            <p className="text-sm text-[color:var(--text-dim)]">
              Cannot reach the desk API. Start the backend with{" "}
              <span className="mono">uvicorn skew.api:app</span> and check{" "}
              <span className="mono">NEXT_PUBLIC_API_BASE</span>.
            </p>
          ) : !focused ? (
            // Three DISTINCT states — a judge opening an unconfigured deploy
            // must see a desk that knows its own condition, not a broken page.
            <div className="max-w-md text-sm leading-relaxed text-[color:var(--text-dim)]">
              {status && !status.broker_connected ? (
                <>
                  <p className="mono mb-2 text-[10px] uppercase tracking-widest">
                    <span
                      className="mr-1.5 inline-block h-[7px] w-[7px] align-middle"
                      style={{ background: "var(--oxide)", borderRadius: "1px" }}
                      aria-hidden
                    />
                    not armed
                  </p>
                  <p>
                    Desk not armed. Market data credentials are not configured on
                    this deployment. The architecture is still fully inspectable —
                    the decision stream on the right is the live audit log.
                  </p>
                </>
              ) : status && status.has_published_state === false ? (
                <>
                  <p className="mono mb-2 text-[10px] uppercase tracking-widest">
                    <span
                      className="mr-1.5 inline-block h-[7px] w-[7px] align-middle"
                      style={{ background: "var(--brass)", borderRadius: "1px" }}
                      aria-hidden
                    />
                    armed
                  </p>
                  <p>
                    Armed. First cycle pending — the desk publishes its first
                    volatility state within a few seconds of boot.
                  </p>
                </>
              ) : universeLoading || states.length === 0 ? (
                <p>Scanning — the first cycle takes a few seconds.</p>
              ) : (
                // Only reachable when symbols exist to select.
                <p>Select a symbol from the rail to see its volatility state.</p>
              )}
            </div>
          ) : (
            <>
              {status && !status.market_open && (
                <p className="mono mb-2 text-[9px] uppercase tracking-wider text-[color:var(--text-dim)]">
                  as of {clockTime(focused.as_of)} · last session
                </p>
              )}
              <VolReadout state={focused} />

              {/* the three instruments, side by side */}
              <div className="mt-5 grid gap-3 md:grid-cols-3">
                <Instrument caption={`skew · front ${focused.skew_slices[0]?.dte ?? "—"}d`}>
                  <SkewCurve
                    slices={focused.skew_slices}
                    spot={focused.spot}
                    rv20={focused.rv_20}
                    redrawKey={`${focused.symbol}-${focused.as_of}`}
                  />
                </Instrument>
                <Instrument caption="realized-vol cone · 252d">
                  <VolCone
                    cone={focused.vol_cone}
                    ivAtm={focused.iv_atm}
                    ivDte={focused.skew_slices[0]?.dte ?? 30}
                  />
                </Instrument>
                <Instrument caption="term structure">
                  <TermStructure points={focused.term_curve} slope={focused.term_slope} />
                </Instrument>
              </div>

              {/* one candidate at full depth */}
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

                {stagedCandidate === null ? (
                  // Empty states are instructions, not "No data".
                  <p className="text-sm text-[color:var(--text-dim)]">
                    No candidates for {focused.symbol} — {focused.note}
                  </p>
                ) : (
                  <>
                    {focusedCandidates.length > 1 && (
                      <div className="mb-3">
                        <CandidateTabs
                          candidates={focusedCandidates}
                          activeId={stagedCandidate.structure.id}
                          onSelect={setFocusId}
                        />
                      </div>
                    )}
                    <div
                      role="tabpanel"
                      id={panelId(stagedCandidate.structure.id)}
                      aria-label={`${stagedCandidate.structure.kind} detail`}
                    >
                      <CandidateCard
                        key={stagedCandidate.structure.id}
                        candidate={stagedCandidate}
                      />
                    </div>
                  </>
                )}
              </section>

              {/* the premium's own history, honest about its window */}
              <div className="mt-6">
                <Instrument caption="vrp history">
                  <VRPHistory symbol={focused.symbol} />
                </Instrument>
              </div>
            </>
          )}
        </main>

        {/* govern */}
        <aside className="flex min-h-0 flex-col border-t border-[color:var(--line)] lg:border-l lg:border-t-0">
          {/* The risk panel yields on short viewports: capped at 55% of the
              column with its own scrollbar, so the audit list below always
              keeps meaningful height. */}
          <div className="shrink-0 lg:max-h-[55%] lg:overflow-y-auto">
            <RiskPanel risk={risk} />
          </div>
          <div className="flex min-h-0 flex-1 flex-col border-t border-[color:var(--line)]">
            <AuditStream decisions={audit ?? []} counts={counts} />
          </div>
        </aside>
      </div>

      <footer className="border-t border-[color:var(--line)] px-4 py-2">
        <p className="mono text-[10px] text-[color:var(--text-dim)]">
          paper trading only · no live code path exists · direction is never an input
        </p>
      </footer>
    </div>
  );
}
