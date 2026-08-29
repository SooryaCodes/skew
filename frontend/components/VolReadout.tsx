"use client";

/**
 * The volatility readout for the focused symbol.
 *
 * The four hero metrics — IV, RV, VRP, TERM — are set in Instrument Serif at
 * dial size. High-contrast serif numerals against dense monospace is the one
 * typographic risk this design takes: they read as values on an instrument's
 * face rather than stats in an app. Everything else stays mono and tabular.
 *
 * The `note` from the backend renders verbatim — it is the sentence that
 * explains the regime, written with the exact threshold that was hit.
 */

import { num, regimeColor, regimeLabel, vol, volPoints } from "@/lib/format";
import type { VolState } from "@/lib/types";

import { SkewCurve } from "./SkewCurve";
import { TermStructure } from "./TermStructure";
import { VolCone } from "./VolCone";
import { VRPHistory } from "./VRPHistory";


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
      <p className="mono text-[10px] uppercase tracking-wider text-[color:var(--text-dim)]">
        {label}
      </p>
      <p className="hero-num mt-1" style={{ color }}>
        {value}
      </p>
      {hint && (
        <p className="mono mt-1 text-[9px] text-[color:var(--text-dim)]">{hint}</p>
      )}
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
          <span className="mono text-[10px] uppercase tracking-widest text-[color:var(--text-dim)]">
            {regimeLabel(state.regime)}
          </span>
        </span>
      </div>

      {/* The dials. VRP carries the regime's metal; the rest stay ink. */}
      <div className="mt-5 grid grid-cols-2 gap-x-8 gap-y-5 sm:grid-cols-4">
        <Dial label="implied vol" value={vol(state.iv_atm)} hint="atm · annualised" />
        <Dial
          label="realized vol"
          value={vol(state.rv_20)}
          hint={`20d · parkinson ${vol(state.rv_parkinson)}`}
        />
        <Dial label="vrp" value={volPoints(state.vrp)} color={color} hint="implied − realized" />
        <Dial label="term" value={volPoints(state.term_slope)} hint={termShape} />
      </div>

      {/* The instruments: the skew itself, the curve over time, the cone, and
          the premium's history. Each reads one clause of the argument the
          dials summarise. */}
      <div className="mt-5 grid gap-3 md:grid-cols-2 2xl:grid-cols-4">
        <Instrument caption={`skew · front ${state.skew_slices[0]?.dte ?? "—"}d`}>
          <SkewCurve
            slices={state.skew_slices}
            spot={state.spot}
            rv20={state.rv_20}
            redrawKey={`${state.symbol}-${state.as_of}`}
          />
        </Instrument>
        <Instrument caption="term structure">
          <TermStructure points={state.term_curve} slope={state.term_slope} />
        </Instrument>
        <Instrument caption="realized-vol cone · 252d">
          <VolCone
            cone={state.vol_cone}
            ivAtm={state.iv_atm}
            ivDte={state.skew_slices[0]?.dte ?? 30}
          />
        </Instrument>
        <Instrument caption="vrp history">
          <VRPHistory symbol={state.symbol} />
        </Instrument>
      </div>

      {/* Rendered verbatim. It names the exact threshold that was hit. */}
      <p className="mt-5 max-w-2xl text-[13px] leading-relaxed text-[color:var(--text)]">
        {state.note}
      </p>

      <p className="mono mt-2 text-[10px] text-[color:var(--text-dim)]">
        rv percentile {state.rv_percentile.toFixed(0)} over its own 252d range ·{" "}
        {state.iv_rank === null
          ? "IV rank unavailable — Alpaca serves no historical IV; this desk builds its own from first run"
          : `IV rank ${state.iv_rank.toFixed(0)} over ${state.iv_rank_window_days} day(s) of self-collected history — not a 52-week rank`}
      </p>
    </section>
  );
}
