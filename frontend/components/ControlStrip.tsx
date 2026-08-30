"use client";

/**
 * The operator's control strip. Rendered ONLY when the tab was opened with
 * ?op=<token> — without it these controls do not exist in the DOM, because a
 * disabled button is an invitation and an absent one is an answer.
 *
 * Three controls, and deliberately no more: run a cycle now, the kill switch,
 * and the universe. No manual trades, no editable tiers or budgets — a
 * human-supplied trade would destroy the autonomy claim, and an editable risk
 * limit is not an earned one.
 */

import { useState } from "react";
import { mutate } from "swr";

import { useCycleStatus, useStatus } from "@/lib/api";
import { ActionError, operatorPost } from "@/lib/operator";

const PHASES = ["scanning", "building", "gating", "deciding"] as const;

function PhaseTrail({ phase, symbol, index, total }: {
  phase: string;
  symbol: string | null;
  index: number;
  total: number;
}) {
  return (
    <span className="flex items-center gap-2">
      {PHASES.map((p) => (
        <span
          key={p}
          className="mono t-fast text-[9px] uppercase tracking-wider"
          style={{
            color: p === phase ? "var(--text)" : "var(--text-dim)",
            borderBottom: p === phase ? "1px solid var(--brass)" : "1px solid transparent",
          }}
        >
          {p}
        </span>
      ))}
      {symbol && (
        <span className="mono text-[9px] text-[color:var(--text-dim)]">
          {symbol} {index}/{total}
        </span>
      )}
    </span>
  );
}

export function ControlStrip() {
  const { data: status } = useStatus();
  const { data: cycle } = useCycleStatus();
  const [error, setError] = useState<string | null>(null);
  const [addSymbol, setAddSymbol] = useState("");
  const [busy, setBusy] = useState(false);

  const running = cycle?.progress.running ?? false;

  const act = async (path: string) => {
    setError(null);
    setBusy(true);
    try {
      await operatorPost(path);
      // Nudge every reader so the change shows up on the next paint, not the
      // next poll interval.
      void mutate(() => true, undefined, { revalidate: true });
    } catch (e) {
      setError(e instanceof ActionError ? e.message : "action failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className="border-b border-[color:var(--line)] bg-[color:var(--panel)] px-4 py-2"
      aria-label="Operator controls"
    >
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <span className="mono text-[9px] uppercase tracking-widest text-[color:var(--text-dim)]">
          operator
        </span>

        {/* 1 — the highest-value control: watch the desk think */}
        {running ? (
          <PhaseTrail
            phase={cycle?.progress.phase ?? "scanning"}
            symbol={cycle?.progress.symbol ?? null}
            index={cycle?.progress.index ?? 0}
            total={cycle?.progress.total ?? 0}
          />
        ) : (
          <button
            type="button"
            disabled={busy}
            onClick={() => act("/api/cycle")}
            className="mono t-fast border border-[color:var(--line)] px-2 py-0.5 text-[10px] uppercase tracking-wider text-[color:var(--text)] hover:border-[color:var(--brass)]"
            style={{ borderRadius: "var(--radius)" }}
          >
            run cycle now
          </button>
        )}

        {/* 2 — the kill switch */}
        <button
          type="button"
          disabled={busy}
          onClick={() => act(`/api/kill?engage=${status?.kill_switch ? "false" : "true"}`)}
          className="mono t-fast border px-2 py-0.5 text-[10px] uppercase tracking-wider"
          style={{
            borderRadius: "var(--radius)",
            borderColor: status?.kill_switch ? "var(--brass)" : "var(--line)",
            color: "var(--text)",
          }}
        >
          {status?.kill_switch ? "release kill switch" : "engage kill switch"}
        </button>

        {/* 3 — the universe */}
        <span className="flex flex-wrap items-center gap-1.5">
          {(status?.universe ?? []).map((symbol) => (
            <span
              key={symbol}
              className="mono flex items-center gap-1 border border-[color:var(--line)] px-1.5 py-0.5 text-[10px]"
              style={{ borderRadius: "var(--radius)" }}
            >
              {symbol}
              <button
                type="button"
                aria-label={`Remove ${symbol} from the universe`}
                onClick={() => act(`/api/universe?symbol=${symbol}&action=remove`)}
                className="t-fast text-[color:var(--text-faint)] hover:text-[color:var(--text)]"
              >
                ×
              </button>
            </span>
          ))}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (addSymbol.trim()) {
                void act(`/api/universe?symbol=${encodeURIComponent(addSymbol.trim())}&action=add`);
                setAddSymbol("");
              }
            }}
          >
            <input
              value={addSymbol}
              onChange={(e) => setAddSymbol(e.target.value)}
              placeholder="+ SYM"
              aria-label="Add a symbol to the universe"
              className="mono w-16 border border-[color:var(--line)] bg-transparent px-1.5 py-0.5 text-[10px] uppercase text-[color:var(--text)] placeholder:text-[color:var(--text-faint)]"
              style={{ borderRadius: "var(--radius)" }}
              maxLength={7}
            />
          </form>
          <span className="mono text-[9px] text-[color:var(--text-dim)]">next cycle</span>
        </span>

        {error && (
          <span className="mono text-[10px] text-[color:var(--text)]" role="alert">
            <span
              className="mr-1.5 inline-block h-[7px] w-[7px] align-middle"
              style={{ background: "var(--brass)", borderRadius: "1px" }}
              aria-hidden
            />
            {error}
          </span>
        )}
      </div>
    </section>
  );
}
