"use client";

/**
 * The universe rail — scan, the first column of the decision sequence.
 *
 * One row per symbol: ticker, VRP, regime. Coloured by `--brass` / `--steel` so
 * the temperature of the whole book reads at a glance before any number is
 * parsed. Selecting a symbol focuses the centre column.
 */

import { regimeColor, regimeLabel, volPoints } from "@/lib/format";
import type { VolState } from "@/lib/types";

interface Props {
  states: VolState[];
  selected: string | null;
  onSelect: (symbol: string) => void;
  loading?: boolean;
}

export function UniverseRail({ states, selected, onSelect, loading }: Props) {
  if (states.length === 0) {
    return (
      <div className="p-3">
        <p className="mono mb-2 text-[10px] uppercase tracking-widest text-[color:var(--text-dim)]">
          universe
        </p>
        {/* Empty states are instructions, never "No data". */}
        <p className="text-xs text-[color:var(--text-dim)]">
          {loading
            ? "Scanning the universe — the first cycle takes a few seconds."
            : "No volatility state yet. The desk publishes one after its first cycle; check the backend is running."}
        </p>
      </div>
    );
  }

  const sorted = [...states].sort((a, b) => b.vrp - a.vrp);

  return (
    <nav className="p-3" aria-label="Universe">
      <p className="mono mb-2 text-[10px] uppercase tracking-widest text-[color:var(--text-dim)]">
        universe · {states.length}
      </p>
      <ul className="space-y-px">
        {sorted.map((state) => {
          const active = state.symbol === selected;
          const color = regimeColor(state.regime);
          // Regime lives in the border bar; words and numerals stay ink, because
          // steel and brass as 9-13px text fail 4.5:1 in one theme or the other.
          return (
            <li key={state.symbol}>
              <button
                type="button"
                onClick={() => onSelect(state.symbol)}
                aria-current={active ? "true" : undefined}
                className="t-fast flex w-full items-baseline gap-2 px-2 py-1.5 text-left"
                style={{
                  background: active ? "var(--panel-alt)" : "transparent",
                  borderLeft: `2px solid ${color}`,
                  opacity: active ? 1 : 0.85,
                  borderRadius: "var(--radius)",
                }}
              >
                <span className="mono w-11 shrink-0 text-[13px]">{state.symbol}</span>
                <span className="mono w-14 shrink-0 text-right text-[13px] text-[color:var(--text)]">
                  {volPoints(state.vrp)}
                </span>
                <span className="mono flex-1 truncate text-right text-[9px] uppercase tracking-wider text-[color:var(--text-dim)]">
                  {regimeLabel(state.regime)}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <p className="mono mt-3 px-2 text-[9px] leading-relaxed text-[color:var(--text-dim)]">
        VRP = implied − realized, in vol points. Positive means the market is
        overpaying for movement.
      </p>
    </nav>
  );
}
