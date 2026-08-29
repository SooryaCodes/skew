"use client";

/**
 * The decision stream.
 *
 * **Refusals are rendered as prominently as fills**, which is the whole point.
 * A system that only shows what it did tells you nothing about its judgement;
 * one that shows every trade it declined, with the failing condition and the
 * numbers behind it, can be read by someone who has never seen the code.
 *
 * The counts strip at the top is the honest headline. A desk that refused forty
 * times and traded twice is doing its job, and that ratio is a more useful
 * summary of this product than any P&L figure would be.
 */

import { clockTime, timeAgo } from "@/lib/format";
import type { Decision, DecisionAction } from "@/lib/types";

const ACTION_STYLE: Record<DecisionAction, { color: string; label: string }> = {
  EXECUTED: { color: "var(--cheap)", label: "filled" },
  // Refusals use --breach because they *are* a failed gate — the one place the
  // colour is spent.
  REFUSED: { color: "var(--breach)", label: "refused" },
  ABSTAINED: { color: "var(--muted)", label: "abstained" },
};

function Entry({ decision, isNewest }: { decision: Decision; isNewest: boolean }) {
  const style = ACTION_STYLE[decision.action] ?? ACTION_STYLE.ABSTAINED;
  return (
    <li
      className={`border-t border-[color:var(--line)] py-2 first:border-t-0 ${
        isNewest ? "audit-enter" : ""
      }`}
    >
      <div className="flex items-baseline gap-2">
        <time
          className="mono shrink-0 text-[10px] text-[color:var(--muted)]"
          dateTime={decision.ts}
          title={timeAgo(decision.ts)}
        >
          {clockTime(decision.ts)}
        </time>
        <span
          className="mono shrink-0 text-[10px] uppercase tracking-wider"
          style={{ color: style.color }}
        >
          {style.label}
        </span>
        {decision.symbol && (
          <span className="mono shrink-0 text-[10px] text-[color:var(--muted)]">
            {decision.symbol}
          </span>
        )}
      </div>
      <p className="mt-0.5 text-[11px] leading-snug text-[color:var(--text)]">{decision.reason}</p>
      {decision.model_rationale && (
        <p className="mt-1 border-l border-[color:var(--line)] pl-2 text-[10px] italic leading-snug text-[color:var(--muted)]">
          {decision.model_rationale}
        </p>
      )}
    </li>
  );
}

interface Props {
  decisions: Decision[];
  counts?: Record<string, number>;
}

export function AuditStream({ decisions, counts }: Props) {
  return (
    <section className="flex min-h-0 flex-col p-3" aria-label="Decision stream">
      <div className="mb-2 flex items-baseline justify-between">
        <p className="mono text-[10px] uppercase tracking-widest text-[color:var(--muted)]">
          audit
        </p>
        {counts && (
          <p className="mono text-[10px] text-[color:var(--muted)]">
            <span style={{ color: "var(--cheap)" }}>{counts.EXECUTED ?? 0}</span>
            {" filled · "}
            <span style={{ color: "var(--breach)" }}>{counts.REFUSED ?? 0}</span>
            {" refused · "}
            {counts.ABSTAINED ?? 0} abstained
          </p>
        )}
      </div>

      {decisions.length === 0 ? (
        <p className="text-xs text-[color:var(--muted)]">
          No decisions yet. The desk logs every refusal and abstention here, not
          only the trades it takes.
        </p>
      ) : (
        <ul className="min-h-0 flex-1 overflow-y-auto pr-1">
          {decisions.map((decision, i) => (
            <Entry key={decision.id} decision={decision} isNewest={i === 0} />
          ))}
        </ul>
      )}
    </section>
  );
}
