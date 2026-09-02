"use client";

/**
 * One candidate: what it is, what it risks, and every gate that judged it.
 *
 * The refusal choreography lives here — the 700ms sequence from
 * docs/03-DESIGN-SYSTEM.md. A breaching stress cell fades to `--oxide` over
 * 200ms, then this card desaturates over 300ms, then the audit entry slides in.
 * It is the only animation in the interface with any drama in it.
 *
 * Gate reasons render **verbatim** from the API. They are written as human copy
 * in the backend precisely so they can appear here untouched; rewording them on
 * the client would put the explanation in two places and let them drift.
 */

import { contractLabel, dollars, money, num, signed, structureLabel } from "@/lib/format";
import type { Candidate, GateResult } from "@/lib/types";

import { PayoffCurve } from "./PayoffCurve";
import { StressGrid } from "./StressGrid";

function GateRow({ gate }: { gate: GateResult }) {
  const state = gate.skipped ? "skipped" : gate.passed ? "pass" : "fail";
  const glyph = state === "skipped" ? "—" : state === "pass" ? "✓" : "✗";
  const color =
    state === "fail"
      ? "var(--oxide)"
      : state === "skipped"
        ? "var(--text-dim)"
        : "var(--verdigris)";

  return (
    <li className="flex gap-2 py-1">
      <span
        className="mono w-3 shrink-0 text-center text-xs leading-5"
        style={{ color }}
        aria-hidden
      >
        {glyph}
      </span>
      <span className="mono w-16 shrink-0 text-[13px] uppercase leading-5 tracking-wider text-[color:var(--text-dim)]">
        {gate.gate}
      </span>
      {/* Reason text stays ink in both states — oxide as 12px text fails 4.5:1
          in dark. The glyph carries the state; a failure also gets weight. */}
      {/* relative: sr-only is absolutely positioned, and without a positioned
          ancestor it resolves against the document — enough off-screen gate
          rows extended the page below the desk shell and broke containment. */}
      <span
        className={`relative text-[14px] leading-5 text-[color:var(--text)] ${
          state === "fail" ? "font-medium" : ""
        }`}
      >
        <span className="sr-only">{state === "fail" ? "Failed: " : "Passed: "}</span>
        {gate.reason}
      </span>
    </li>
  );
}

export function CandidateCard({ candidate }: { candidate: Candidate }) {
  const s = candidate.structure;
  const refused = !candidate.passed_all;
  const failed = candidate.gates.filter((g) => !g.passed && !g.skipped);

  return (
    <article
      className={`panel p-4 ${refused ? "card-refused" : ""}`}
      aria-label={`${structureLabel(s.kind)} on ${s.symbol}, ${
        refused ? "refused" : "passed all gates"
      }`}
    >
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="font-display text-[length:var(--fs-base)]">
          {structureLabel(s.kind)}
          <span className="mono ml-2 text-[color:var(--text-dim)] text-xs">
            {s.legs
              .map((l) => l.strike)
              .sort((a, b) => a - b)
              .join(" / ")}
          </span>
        </h3>
        <span className="mono text-[13px] text-[color:var(--text-dim)]">
          {s.dte}d · {s.qty}x
        </span>
      </header>

      {/* Legs */}
      <ul className="mt-3 space-y-1">
        {[...s.legs]
          .sort((a, b) => a.right.localeCompare(b.right) || a.strike - b.strike)
          .map((leg) => (
            <li key={leg.symbol} className="flex items-baseline gap-2 text-[13px]">
              <span className="flex w-11 shrink-0 items-center gap-1">
                <span
                  className="inline-block h-[6px] w-[6px] shrink-0"
                  style={{
                    background: leg.side === "SELL" ? "var(--brass)" : "var(--steel)",
                    borderRadius: "1px",
                  }}
                  aria-hidden
                />
                <span className="mono uppercase text-[color:var(--text-dim)]">{leg.side}</span>
              </span>
              <span className="contract flex-1 truncate text-[color:var(--text-dim)]">
                {contractLabel(leg.symbol)}
              </span>
              <span className="mono text-[color:var(--text-dim)]">{num(leg.mid, 2)}</span>
              <span className="mono w-12 text-right text-[color:var(--text-dim)]">
                Δ {signed(leg.delta, 2)}
              </span>
            </li>
          ))}
      </ul>

      {/* The three numbers that matter */}
      <dl className="mt-3 grid grid-cols-3 gap-2 border-t border-[color:var(--line)] pt-3">
        <div>
          <dt className="mono text-[12px] uppercase tracking-wider text-[color:var(--text-dim)]">
            {s.net_credit >= 0 ? "credit" : "debit"}
          </dt>
          <dd className="mono text-[length:var(--fs-base)]">{dollars(s.net_credit, 2)}</dd>
        </div>
        <div>
          <dt className="mono text-[12px] uppercase tracking-wider text-[color:var(--text-dim)]">
            max loss
          </dt>
          <dd className="mono text-[length:var(--fs-base)]">{dollars(s.max_loss, 2)}</dd>
        </div>
        <div>
          <dt className="mono text-[12px] uppercase tracking-wider text-[color:var(--text-dim)]">
            net vega
          </dt>
          <dd className="mono text-[length:var(--fs-base)]">{signed(s.net_vega, 1)}</dd>
        </div>
      </dl>

      <p className="mono mt-2 text-[12px] text-[color:var(--text-dim)]">
        breakeven {s.breakevens.map((b) => num(b, 2)).join(" / ")} · max profit{" "}
        {dollars(s.max_profit, 2)} · theta {signed(s.net_theta, 2)}
      </p>

      <div className="mt-3 border-t border-[color:var(--line)] pt-3">
        <PayoffCurve structure={s} rv20={candidate.vol_state?.rv_20} />
      </div>

      <div className="mt-3 border-t border-[color:var(--line)] pt-3">
        <StressGrid cells={candidate.stress_grid} maxLoss={s.max_loss} refused={refused} />
      </div>

      <ul className="mt-3 border-t border-[color:var(--line)] pt-2">
        {candidate.gates.map((gate) => (
          <GateRow key={gate.gate} gate={gate} />
        ))}
      </ul>

      <footer className="mt-2 border-t border-[color:var(--line)] pt-2">
        <p className="mono flex items-center gap-1.5 text-[13px] uppercase tracking-wider text-[color:var(--text)]">
          <span
            className="inline-block h-[7px] w-[7px] shrink-0"
            style={{
              background: refused ? "var(--oxide)" : "var(--verdigris)",
              borderRadius: "1px",
            }}
            aria-hidden
          />
          {refused
            ? `refused — ${failed.map((g) => g.gate).join(", ") || "unknown"}`
            : `passed all gates · worst case ${money(candidate.worst_case, 0)}`}
        </p>
      </footer>
    </article>
  );
}
