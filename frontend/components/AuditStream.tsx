"use client";

/**
 * The decision stream, grouped.
 *
 * Eight names abstaining every five minutes with near-identical sentences is
 * noise that buries the signal. Consecutive abstentions collapse to one line
 * with a count badge, expanding on click to the full entries.
 *
 * FILLS AND REFUSALS NEVER COLLAPSE. They render in full, complete reason
 * text, every time — those two are the product; the abstentions are context
 * until asked for.
 */

import { useMemo, useState } from "react";

import { clockTime, timeAgo } from "@/lib/format";
import type { Decision, DecisionAction } from "@/lib/types";

const ACTION_STYLE: Record<DecisionAction, { color: string; label: string }> = {
  EXECUTED: { color: "var(--verdigris)", label: "filled" },
  REFUSED: { color: "var(--oxide)", label: "refused" },
  ABSTAINED: { color: "var(--line)", label: "abstained" },
};

type Group =
  | { kind: "single"; entry: Decision }
  | { kind: "collapsed"; entries: Decision[]; key: string };

/** Consecutive ABSTAINED runs of 2+ collapse; everything else stands alone. */
function groupDecisions(decisions: Decision[]): Group[] {
  const groups: Group[] = [];
  let run: Decision[] = [];

  const flush = () => {
    if (run.length >= 2) {
      groups.push({ kind: "collapsed", entries: run, key: run[0]!.id });
    } else {
      run.forEach((entry) => groups.push({ kind: "single", entry }));
    }
    run = [];
  };

  for (const decision of decisions) {
    if (decision.action === "ABSTAINED") {
      run.push(decision);
    } else {
      flush();
      groups.push({ kind: "single", entry: decision });
    }
  }
  flush();
  return groups;
}

/** A short shared label when the run's reasons rhyme; honest when they don't. */
function runLabel(entries: Decision[]): string {
  const reasons = entries.map((e) => e.reason);
  if (reasons.every((r) => r.includes("fairly priced"))) return "volatility fairly priced";
  if (reasons.every((r) => r.includes("refused by the gate chain"))) {
    return "all candidates refused by the gate chain";
  }
  if (reasons.every((r) => r.includes("percentile"))) return "realized vol too hot";
  if (reasons.every((r) => r.includes("selector"))) return "selector abstained";
  if (reasons.every((r) => r.includes("DRY RUN"))) return "dry run";
  return "mixed reasons";
}

function Marker({ color }: { color: string }) {
  return (
    <span
      className="inline-block h-[7px] w-[7px] shrink-0"
      style={{ background: color, borderRadius: "1px" }}
      aria-hidden
    />
  );
}

function FullEntry({ decision, isNewest }: { decision: Decision; isNewest: boolean }) {
  const style = ACTION_STYLE[decision.action] ?? ACTION_STYLE.ABSTAINED;
  return (
    <li
      className={`border-t border-[color:var(--line)] py-2 first:border-t-0 ${
        isNewest ? "audit-enter" : ""
      }`}
    >
      <div className="flex items-center gap-2">
        <time
          className="mono shrink-0 text-[10px] text-[color:var(--text-dim)]"
          dateTime={decision.ts}
          title={timeAgo(decision.ts)}
        >
          {clockTime(decision.ts)}
        </time>
        <Marker color={style.color} />
        <span className="mono text-[10px] uppercase tracking-wider text-[color:var(--text)]">
          {style.label}
        </span>
        {decision.symbol && (
          <span className="mono shrink-0 text-[10px] text-[color:var(--text-dim)]">
            {decision.symbol}
          </span>
        )}
      </div>
      {/* Complete reason text. Fills and refusals are never truncated. */}
      <p className="mt-0.5 text-[11px] leading-snug text-[color:var(--text)]">{decision.reason}</p>
      {decision.model_rationale && (
        <p className="mt-1 border-l border-[color:var(--line)] pl-2 text-[10px] italic leading-snug text-[color:var(--text-dim)]">
          {decision.model_rationale}
        </p>
      )}
    </li>
  );
}

function CollapsedRun({ entries }: { entries: Decision[] }) {
  const [open, setOpen] = useState(false);
  const newest = entries[0]!;
  const symbols = entries.map((e) => e.symbol).filter(Boolean);

  return (
    <li className="border-t border-[color:var(--line)] py-2 first:border-t-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="t-fast flex w-full items-center gap-2 text-left"
      >
        <time className="mono shrink-0 text-[10px] text-[color:var(--text-dim)]" dateTime={newest.ts}>
          {clockTime(newest.ts)}
        </time>
        <Marker color="var(--line)" />
        <span className="min-w-0 flex-1 truncate text-[11px] text-[color:var(--text-dim)]">
          {symbols.length > 0 ? `${symbols.length} names abstained` : `${entries.length} abstentions`}
          {" — "}
          {runLabel(entries)}
        </span>
        <span
          className="mono shrink-0 border border-[color:var(--line)] px-1 text-[9px] text-[color:var(--text-dim)]"
          style={{ borderRadius: "var(--radius)" }}
        >
          {open ? "−" : `+${entries.length}`}
        </span>
      </button>

      {open && (
        <ul className="mt-1 border-l border-[color:var(--line)] pl-2">
          {entries.map((entry) => (
            <li key={entry.id} className="py-1">
              <p className="mono text-[10px] text-[color:var(--text-dim)]">
                {clockTime(entry.ts)} · {entry.symbol ?? "—"}
              </p>
              <p className="text-[11px] leading-snug text-[color:var(--text)]">{entry.reason}</p>
              {entry.model_rationale && (
                <p className="mt-0.5 text-[10px] italic leading-snug text-[color:var(--text-dim)]">
                  {entry.model_rationale}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

interface Props {
  decisions: Decision[];
  counts?: Record<string, number>;
}

export function AuditStream({ decisions, counts }: Props) {
  const groups = useMemo(() => groupDecisions(decisions), [decisions]);

  return (
    <section className="flex min-h-0 flex-col p-3" aria-label="Decision stream">
      <div className="mb-2 flex items-baseline justify-between">
        <p className="mono text-[10px] uppercase tracking-widest text-[color:var(--text-dim)]">
          audit
        </p>
        {counts && (
          <p className="mono text-[10px] text-[color:var(--text-dim)]">
            {counts.EXECUTED ?? 0} filled · {counts.REFUSED ?? 0} refused ·{" "}
            {counts.ABSTAINED ?? 0} abstained
          </p>
        )}
      </div>

      {groups.length === 0 ? (
        <p className="text-xs text-[color:var(--text-dim)]">
          No decisions yet. The desk logs every refusal and abstention here, not
          only the trades it takes.
        </p>
      ) : (
        <ul className="min-h-0 flex-1 overflow-y-auto pr-1">
          {groups.map((group, i) =>
            group.kind === "single" ? (
              <FullEntry key={group.entry.id} decision={group.entry} isNewest={i === 0} />
            ) : (
              <CollapsedRun key={group.key} entries={group.entries} />
            ),
          )}
        </ul>
      )}
    </section>
  );
}
