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

// State is the marker's colour; the word itself is neutral ink, because the
// metals fail 4.5:1 as 10px text in one theme or the other. Refusals mark with
// --oxide because they are a failed gate — the one place that colour is spent.
const ACTION_STYLE: Record<DecisionAction, { color: string; label: string }> = {
  EXECUTED: { color: "var(--verdigris)", label: "filled" },
  REFUSED: { color: "var(--oxide)", label: "refused" },
  ABSTAINED: { color: "var(--line)", label: "abstained" },
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
          className="mono shrink-0 text-[10px] text-[color:var(--text-dim)]"
          dateTime={decision.ts}
          title={timeAgo(decision.ts)}
        >
          {clockTime(decision.ts)}
        </time>
        <span className="flex shrink-0 items-center gap-1.5">
          <span
            className="inline-block h-[7px] w-[7px] shrink-0"
            style={{ background: style.color, borderRadius: "1px" }}
            aria-hidden
          />
          <span className="mono text-[10px] uppercase tracking-wider text-[color:var(--text)]">
            {style.label}
          </span>
        </span>
        {decision.symbol && (
          <span className="mono shrink-0 text-[10px] text-[color:var(--text-dim)]">
            {decision.symbol}
          </span>
        )}
      </div>
      <p className="mt-0.5 text-[11px] leading-snug text-[color:var(--text)]">{decision.reason}</p>
      {decision.model_rationale && (
        <p className="mt-1 border-l border-[color:var(--line)] pl-2 text-[10px] italic leading-snug text-[color:var(--text-dim)]">
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

      {decisions.length === 0 ? (
        <p className="text-xs text-[color:var(--text-dim)]">
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
