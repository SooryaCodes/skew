"use client";

/**
 * The stress grid — the secondary signature element, and the money shot.
 *
 * 7 columns of price shock by 4 rows of IV shock, each cell a small square
 * shaded by outcome. Almost always calm. When one cell breaches it goes
 * `--oxide`, and the candidate card desaturates around it.
 *
 * Hand-rolled CSS grid rather than a chart library. It is 28 squares — a chart
 * library would be more friction than help, per docs/02-TECH-STACK.md.
 *
 * `--oxide` red appears here and only here in the whole interface, and only on
 * a genuinely breaching cell. That is the rule that makes the refusal land: the
 * eye goes straight to it because nothing else on the screen is that colour.
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

/** Cell background: calm cells barely register, so a breach is unmissable. */
function cellStyle(cell: StressCell, worstPnl: number, maxLoss: number): React.CSSProperties {
  if (cell.breached) {
    // Field + outline come from .cell-breach; ink stays --text so the numeral
    // clears 4.5:1 in both themes. Solid oxide under a numeral does not.
    return { color: "var(--text)" };
  }
  if (cell.pnl >= 0) {
    const strength = Math.min(1, cell.pnl / Math.max(1, Math.abs(worstPnl) * 0.25));
    return {
      background: `color-mix(in srgb, var(--steel) ${8 + strength * 16}%, var(--panel-alt))`,
      color: "var(--text)",
    };
  }
  const severity = Math.min(1, Math.abs(cell.pnl) / Math.max(1, maxLoss));
  return {
    background: `color-mix(in srgb, var(--brass) ${6 + severity * 30}%, var(--panel-alt))`,
    color: severity > 0.6 ? "var(--text)" : "var(--text-dim)",
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
    return { priceShocks, ivShocks, lookup, worst, count: slice.length };
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

        {view.ivShocks.map((iv) => (
          <div key={`row-${iv}`} className="contents">
            <span className="mono self-center pr-1 text-right text-[10px] text-[color:var(--text-dim)]">
              ×{iv.toFixed(1)}
            </span>
            {view.priceShocks.map((px) => {
              const cell = view.lookup.get(`${px}|${iv}`);
              if (!cell) {
                return <span key={`${px}-${iv}`} className="h-7" />;
              }
              const isWorst = cell === view.worst;
              return (
                <button
                  key={`${px}-${iv}`}
                  type="button"
                  onMouseEnter={() => setHovered(cell)}
                  onFocus={() => setHovered(cell)}
                  aria-label={`${px} sigma, IV times ${iv}, profit and loss ${money(cell.pnl, 0)}${
                    cell.breached ? ", breached" : ""
                  }`}
                  className={`mono h-7 text-[10px] tabular-nums ${
                    cell.breached ? "cell-breach" : "t-fast"
                  }`}
                  style={{
                    ...cellStyle(cell, view.worst?.pnl ?? -1, maxLoss),
                    borderRadius: "var(--radius)",
                    outline: isWorst && !cell.breached ? "1px solid var(--line)" : undefined,
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

      {detail && (
        <p className="mt-2 text-[11px] text-[color:var(--text-dim)]">
          <span className="mono">
            {detail.price_shock > 0 ? `+${detail.price_shock}` : detail.price_shock}σ
          </span>
          {" with IV "}
          <span className="mono">
            {detail.iv_shock === 1
              ? "unchanged"
              : `${detail.iv_shock > 1 ? "+" : "−"}${Math.abs(
                  (detail.iv_shock - 1) * 100,
                ).toFixed(0)}%`}
          </span>
          {" → "}
          <span className="mono" style={{ color: detail.breached ? "var(--oxide)" : undefined }}>
            {money(detail.pnl, 0)}
          </span>
          {detail === view.worst && !hovered && (
            <span className="text-[color:var(--text-dim)]">
              {" "}
              · worst cell at this time point
            </span>
          )}
          {refused && detail.breached && (
            <span style={{ color: "var(--oxide)" }}> · breaches the tier budget</span>
          )}
        </p>
      )}
    </div>
  );
}
