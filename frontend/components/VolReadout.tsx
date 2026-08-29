"use client";

/**
 * The volatility readout for the focused symbol.
 *
 * IV, RV, VRP, term slope. Mono, tabular figures, explicit signs on anything
 * that can be negative. The `note` from the backend renders verbatim — it is
 * the sentence that explains the regime, written with the exact threshold that
 * was hit.
 */

import { num, regimeColor, regimeLabel, vol, volPoints } from "@/lib/format";
import type { VolState } from "@/lib/types";

function Stat({
  label,
  value,
  color,
  hint,
}: {
  label: string;
  value: string;
  color?: string;
  hint?: string;
}) {
  return (
    <div>
      <p className="mono text-[10px] uppercase tracking-wider text-[color:var(--muted)]">
        {label}
      </p>
      <p className="mono text-[length:var(--fs-md)] leading-tight" style={{ color }}>
        {value}
      </p>
      {hint && <p className="mono text-[9px] text-[color:var(--muted)]">{hint}</p>}
    </div>
  );
}

export function VolReadout({ state }: { state: VolState }) {
  const color = regimeColor(state.regime);
  const termShape =
    state.term_slope > 0.005
      ? "contango"
      : state.term_slope < -0.005
        ? "backwardation"
        : "flat";

  return (
    <section aria-label={`Volatility state for ${state.symbol}`}>
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h2 className="font-display text-[length:var(--fs-lg)] leading-none">{state.symbol}</h2>
        <span className="mono text-[length:var(--fs-base)] text-[color:var(--muted)]">
          {num(state.spot, 2)}
        </span>
        <span
          className="mono text-[10px] uppercase tracking-widest"
          style={{ color }}
        >
          {regimeLabel(state.regime)}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-5">
        <Stat label="IV atm" value={vol(state.iv_atm)} hint="annualised" />
        <Stat label="RV 20d" value={vol(state.rv_20)} hint={`park ${vol(state.rv_parkinson)}`} />
        <Stat label="VRP" value={volPoints(state.vrp)} color={color} hint="iv − rv" />
        <Stat
          label="term"
          value={volPoints(state.term_slope)}
          hint={termShape}
        />
        <Stat
          label="RV %ile"
          value={state.rv_percentile.toFixed(0)}
          hint="252d, own range"
        />
      </div>

      {/* Rendered verbatim. It names the exact threshold that was hit. */}
      <p className="mt-4 max-w-2xl text-[13px] leading-relaxed text-[color:var(--text)]">
        {state.note}
      </p>

      <p className="mono mt-2 text-[10px] text-[color:var(--muted)]">
        {state.iv_rank === null
          ? "IV rank unavailable — Alpaca serves no historical implied volatility, so this desk builds its own from first run."
          : `IV rank ${state.iv_rank.toFixed(0)} over ${state.iv_rank_window_days} day(s) of self-collected history — not a 52-week rank.`}
      </p>
    </section>
  );
}
