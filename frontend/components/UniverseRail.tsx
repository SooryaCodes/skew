"use client";

/**
 * The universe rail — scan, the first column of the decision sequence.
 *
 * Sorted by |VRP|, so the widest gaps sit at the top regardless of sign: a
 * −13.6 is exactly as interesting as a +13.6, and both belong above a +1.4.
 * The regime lives in the border bar's metal; words and numerals stay ink,
 * because steel and brass as 9–13px text fail 4.5:1 in one theme or the other.
 */

import { regimeColor, regimeLabel, volPoints } from "@/lib/format";
import type { PerSymbolSummary, VolState } from "@/lib/types";

interface Props {
  states: VolState[];
  selected: string | null;
  onSelect: (symbol: string) => void;
  loading?: boolean;
  /** All-time decision depth per symbol, from the audit record. */
  perSymbol?: Record<string, PerSymbolSummary>;
}

const OUTCOME_DOT: Record<string, { color: string; label: string }> = {
  EXECUTED: { color: "var(--positive)", label: "filled" },
  REFUSED: { color: "var(--negative)", label: "refused" },
  ABSTAINED: { color: "var(--text-faint)", label: "abstained" },
};

export function UniverseRail({ states, selected, onSelect, loading, perSymbol }: Props) {
  if (states.length === 0) {
    return (
      <div className="p-3">
        <p className="mono mb-2 text-[12px] uppercase tracking-widest text-[color:var(--text-dim)]">
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

  const sorted = [...states].sort((a, b) => Math.abs(b.vrp) - Math.abs(a.vrp));

  return (
    <nav className="p-3" aria-label="Universe">
      <p className="mono mb-2 text-[12px] uppercase tracking-widest text-[color:var(--text-dim)]">
        universe · {states.length}
      </p>
      <ul className="space-y-px">
        {sorted.map((state) => {
          const active = state.symbol === selected;
          const color = regimeColor(state.regime);
          return (
            <li key={state.symbol}>
              {/* keyed by as_of so a fresh cycle re-mounts the row and the
                  one-shot pulse marks the change — restrained, then settles */}
              <button
                key={`${state.symbol}-${state.as_of}`}
                type="button"
                onClick={() => onSelect(state.symbol)}
                aria-current={active ? "true" : undefined}
                title={perSymbol?.[state.symbol]?.last_reason}
                className="t-fast pulse-once flex w-full flex-col gap-0.5 px-2 py-1.5 text-left"
                style={{
                  background: active ? "var(--panel-alt)" : "transparent",
                  // Inactive rows dim the BAR, never the text — 85% opacity on
                  // the whole row pushed light-theme text-dim to 4.05:1.
                  borderLeft: `2px solid ${active ? color : `color-mix(in srgb, ${color} 55%, var(--ground))`}`,
                  borderRadius: "var(--radius)",
                }}
              >
                <span className="flex w-full items-baseline gap-2">
                  <span className="mono w-11 shrink-0 text-[15px]">{state.symbol}</span>
                  <span className="mono w-14 shrink-0 text-right text-[15px] text-[color:var(--text)]">
                    {volPoints(state.vrp)}
                  </span>
                  <span className="mono flex-1 truncate text-right text-[12px] uppercase tracking-wider text-[color:var(--text-dim)]">
                    {regimeLabel(state.regime)}
                  </span>
                </span>
                {/* what the desk has actually DONE with this name — all-time
                    count and the latest outcome, reason on hover */}
                {perSymbol?.[state.symbol] && (
                  <span className="mono flex w-full items-center gap-1.5 text-[11px] text-[color:var(--text-faint)]">
                    {perSymbol[state.symbol]!.total.toLocaleString()} decisions
                    <span
                      className="ml-auto inline-block h-[5px] w-[5px] rounded-full"
                      style={{
                        background:
                          OUTCOME_DOT[perSymbol[state.symbol]!.last_action]?.color ??
                          "var(--text-faint)",
                      }}
                      aria-hidden
                    />
                    last {OUTCOME_DOT[perSymbol[state.symbol]!.last_action]?.label ?? "—"}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
      <p className="mono mt-3 px-2 text-[12px] leading-relaxed text-[color:var(--text-dim)]">
        sorted by |VRP| — the widest gap between implied and realized sits on
        top, whichever way it points.
      </p>
    </nav>
  );
}
