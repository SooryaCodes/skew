"use client";

/**
 * The hero dials for the focused symbol — IV, RV, VRP, TERM in Instrument
 * Serif at dial size, each with a small mono caption. High-contrast serif
 * numerals against dense monospace read as values on an instrument's face
 * rather than stats in an app; it is the one typographic risk this design
 * takes. Everything else stays mono and tabular.
 *
 * The `note` renders verbatim — the sentence that explains the regime, written
 * in the backend with the exact threshold that was hit.
 */

import { num, regimeColor, regimeLabel, vol, volPoints } from "@/lib/format";
import type { VolState } from "@/lib/types";

function Dial({
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
      <p className="mono text-[12px] uppercase tracking-wider text-[color:var(--text-dim)]">
        {label}
      </p>
      <p className="hero-num mt-1" style={{ color }}>
        {value}
      </p>
      {hint && <p className="mono mt-1 text-[12px] text-[color:var(--text-dim)]">{hint}</p>}
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
        <span className="mono text-[length:var(--fs-base)] text-[color:var(--text-dim)]">
          {num(state.spot, 2)}
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block h-[7px] w-[7px]"
            style={{ background: color, borderRadius: "1px" }}
            aria-hidden
          />
          <span className="mono text-[12px] uppercase tracking-widest text-[color:var(--text-dim)]">
            {regimeLabel(state.regime)}
          </span>
        </span>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-x-8 gap-y-5 sm:grid-cols-4">
        <Dial label="iv atm" value={vol(state.iv_atm)} hint="annualised" />
        <Dial
          label="rv 20d"
          value={vol(state.rv_20)}
          hint={`park ${vol(state.rv_parkinson)}`}
        />
        <Dial label="vrp" value={volPoints(state.vrp)} color={color} hint="iv − rv" />
        <Dial label="term" value={volPoints(state.term_slope)} hint={termShape} />
      </div>

      {/* Rendered verbatim. It names the exact threshold that was hit. */}
      <p className="mt-5 max-w-2xl text-[15px] leading-relaxed text-[color:var(--text)]">
        {state.note}
      </p>

      <p className="mono mt-2 text-[12px] text-[color:var(--text-dim)]">
        rv percentile {state.rv_percentile.toFixed(0)} over its own 252d range ·{" "}
        {state.iv_rank === null
          ? `IV rank unavailable — building history, ${state.iv_rank_window_days} day(s) collected (20 needed; Alpaca serves no historical IV)`
          : `IV rank ${state.iv_rank.toFixed(0)} over ${state.iv_rank_window_days} day(s) of self-collected history — not a 52-week rank`}
      </p>
    </section>
  );
}
