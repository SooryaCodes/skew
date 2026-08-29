"use client";

/**
 * The stress grid — the centrepiece.
 *
 * P&L maps to a CONTINUOUS ramp, not four buckets: verdigris through neutral
 * into brass-dim as losses deepen, oxide only inside the breach region. The
 * breach boundary is DRAWN — a 1.5px --oxide contour between passing and
 * failing cells — because a visible frontier is far stronger than shaded
 * squares: the eye reads a line on a map where it would skim a heat blob.
 *
 * The worst cell gets a ring and a callout naming its coordinates. Switching
 * NOW / MID-LIFE / EXPIRY cross-fades each cell's colour in place — same grid,
 * new weather — rather than jumping.
 */

import { useMemo, useState } from "react";

import { money } from "@/lib/format";
import type { StressCell, TimePoint } from "@/lib/types";

const TIME_POINTS: Array<{ key: TimePoint; label: string }> = [
  { key: "NOW", label: "now" },
  { key: "MID", label: "mid-life" },
  { key: "EXPIRY", label: "expiry" },
];

interface Props {
  cells: StressCell[];
  maxLoss: number;
  refused?: boolean;
}

/** The continuous ramp. Intensity from the cell's own share of the extremes. */
function cellStyle(cell: StressCell, maxProfit: number, maxLoss: number): React.CSSProperties {
  const base: React.CSSProperties = {
    borderRadius: "var(--radius)",
    // The cross-fade: colours transition in place when the time point flips.
    transition: "background-color 260ms ease, border-color 260ms ease, color 260ms ease",
  };
  if (cell.breached) {
    const t = Math.min(1, Math.abs(cell.pnl) / Math.max(1, maxLoss));
    return {
      ...base,
      background: `color-mix(in srgb, var(--oxide) ${18 + t * 22}%, var(--panel))`,
      color: "var(--text)",
    };
  }
  if (cell.pnl >= 0) {
    const t = Math.min(1, cell.pnl / Math.max(1, maxProfit));
    return {
      ...base,
      background: `color-mix(in srgb, var(--verdigris) ${4 + t * 26}%, var(--panel))`,
      color: "var(--text-dim)",
    };
  }
  const t = Math.min(1, Math.abs(cell.pnl) / Math.max(1, maxLoss));
  return {
    ...base,
    background: `color-mix(in srgb, var(--brass-dim) ${4 + t * 46}%, var(--panel))`,
    color: t > 0.55 ? "var(--text)" : "var(--text-dim)",
  };
}

export function StressGrid({ cells, maxLoss, refused = false }: Props) {
  const [timePoint, setTimePoint] = useState<TimePoint>("MID");
  const [hovered, setHovered] = useState<StressCell | null>(null);

  const view = useMemo(() => {
    const slice = cells.filter((c) => c.time_point === timePoint);
    const priceShocks = [...new Set(slice.map((c) => c.price_shock))].sort((a, b) => a - b);
    const ivShocks = [...new Set(slice.map((c) => c.iv_shock))].sort((a, b) => a - b);
    const lookup = new Map(slice.map((c) => [`${c.price_shock}|${c.iv_shock}`, c]));
    const worst = slice.reduce<StressCell | null>(
      (acc, c) => (acc === null || c.pnl < acc.pnl ? c : acc),
      null,
    );
    const maxProfit = Math.max(1, ...slice.map((c) => c.pnl));

    // The contour: a cell's side gets the oxide line where its neighbour's
    // breached state differs. Drawn on the breached side only, so the frontier
    // is a single crisp line hugging the failing region.
    const at = (pi: number, ii: number) =>
      lookup.get(`${priceShocks[pi]}|${ivShocks[ii]}`) ?? null;
    const contour = (pi: number, ii: number) => {
      const cell = at(pi, ii);
      if (!cell?.breached) return {};
      const edge = "1.5px solid var(--oxide)";
      const style: React.CSSProperties = {};
      const left = pi > 0 ? at(pi - 1, ii) : null;
      const right = pi < priceShocks.length - 1 ? at(pi + 1, ii) : null;
      const up = ii > 0 ? at(pi, ii - 1) : null;
      const down = ii < ivShocks.length - 1 ? at(pi, ii + 1) : null;
      if (left && !left.breached) style.borderLeft = edge;
      if (right && !right.breached) style.borderRight = edge;
      if (up && !up.breached) style.borderTop = edge;
      if (down && !down.breached) style.borderBottom = edge;
      return style;
    };

    return { priceShocks, ivShocks, lookup, worst, maxProfit, contour, at };
  }, [cells, timePoint]);

  if (cells.length === 0) {
    return (
      <p className="text-xs text-[color:var(--text-dim)]">
        No stress grid — the candidate was refused before it was priced.
      </p>
    );
  }

  const detail = hovered ?? view.worst;

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <span className="mono text-[11px] uppercase tracking-widest text-[color:var(--text-dim)]">
          stress · {cells.length} scenarios
        </span>
        <div className="flex gap-1" role="tablist" aria-label="Time point">
          {TIME_POINTS.map((tp) => (
            <button
              key={tp.key}
              type="button"
              role="tab"
              aria-selected={timePoint === tp.key}
              onClick={() => setTimePoint(tp.key)}
              className="mono t-fast px-1.5 py-0.5 text-[10px] uppercase tracking-wider"
              style={{
                color: timePoint === tp.key ? "var(--text)" : "var(--text-dim)",
                borderBottom:
                  timePoint === tp.key ? "1px solid var(--text)" : "1px solid transparent",
              }}
            >
              {tp.label}
            </button>
          ))}
        </div>
      </div>

      <div
        className="grid gap-[2px]"
        style={{ gridTemplateColumns: `2.6rem repeat(${view.priceShocks.length}, 1fr)` }}
        onMouseLeave={() => setHovered(null)}
      >
        <span aria-hidden />
        {view.priceShocks.map((shock) => (
          <span
            key={`h-${shock}`}
            className="mono pb-1 text-center text-[10px] text-[color:var(--text-dim)]"
          >
            {shock > 0 ? `+${shock}` : shock}σ
          </span>
        ))}

        {view.ivShocks.map((iv, ii) => (
          <div key={`row-${iv}`} className="contents">
            <span className="mono self-center pr-1 text-right text-[10px] text-[color:var(--text-dim)]">
              ×{iv.toFixed(1)}
            </span>
            {view.priceShocks.map((px, pi) => {
              const cell = view.at(pi, ii);
              if (!cell) return <span key={`${px}-${iv}`} className="h-7" />;
              const isWorst = cell === view.worst;
              const contour = view.contour(pi, ii);
              const hasContour = Object.keys(contour).length > 0;
              return (
                <button
                  key={`${px}-${iv}`}
                  type="button"
                  onMouseEnter={() => setHovered(cell)}
                  onFocus={() => setHovered(cell)}
                  aria-label={`${px} sigma, IV times ${iv}, profit and loss ${money(cell.pnl, 0)}${
                    cell.breached ? ", breaches the budget" : ""
                  }${isWorst ? ", worst cell" : ""}`}
                  className={`mono h-7 text-[10px] tabular-nums${
                    hasContour ? " contour-in" : ""
                  }${isWorst ? " cell-worst" : ""}`}
                  style={{
                    ...cellStyle(cell, view.maxProfit, maxLoss),
                    ...contour,
                  }}
                >
                  {Math.abs(cell.pnl) >= 1000
                    ? `${cell.pnl < 0 ? "−" : "+"}${(Math.abs(cell.pnl) / 1000).toFixed(1)}k`
                    : Math.round(cell.pnl)}
                </button>
              );
            })}
          </div>
        ))}
      </div>

      {/* the callout: worst cell by default, hovered cell when exploring */}
      {detail && (
        <p className="mono mt-2 text-[10px] text-[color:var(--text-dim)]">
          {detail === view.worst && !hovered ? "◯ worst " : ""}
          {detail.price_shock > 0 ? `+${detail.price_shock}` : detail.price_shock}σ, iv{" "}
          {detail.iv_shock === 1
            ? "unchanged"
            : `${detail.iv_shock > 1 ? "+" : "−"}${Math.abs((detail.iv_shock - 1) * 100).toFixed(0)}%`}
          {" → "}
          <span style={{ color: "var(--text)" }}>{money(detail.pnl, 0)}</span>
          {detail.breached && (
            <span>
              {" "}
              · past the budget line
              {refused ? " — this is why the gate refused" : ""}
            </span>
          )}
        </p>
      )}
    </div>
  );
}
