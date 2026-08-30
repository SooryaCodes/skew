"use client";

/**
 * The decision stream, grouped by (outcome, reason template).
 *
 * Eight consecutive identical budget refusals teach nothing seven times.
 * Runs whose sentences differ only in their particulars — the numbers, the
 * ticker — show the FIRST entry in full and fold the rest into "+N more,
 * same reason", expandable. A genuinely distinct reason never matches the
 * template and always renders in full. Fills never collapse at all.
 */

import Link from "next/link";
import { useMemo, useState } from "react";

import { clockTime, timeAgo } from "@/lib/format";
import type { Decision, DecisionAction } from "@/lib/types";

/** Strip the legacy tier-promotion tail from rows written before it was
 *  removed at the source — identical on every refusal, already in the risk
 *  panel, and it doubled the length of each entry. */
function stripPromotionTail(reason: string): string {
  return reason.replace(/\s*Tier \d \([^)]*\) needs [^.]*\.\s*$/, "").trim();
}

const CHECK_LABEL: Record<string, string> = {
  per_trade: "per-trade cap",
  portfolio: "portfolio cap",
  capacity: "capacity",
};

/** "budget · per-trade cap" — the scannable key, pulled out of the prose. */
function failingGateLine(decision: Decision): string | null {
  if (decision.action !== "REFUSED") return null;
  const gates = decision.detail?.gates as
    | Array<{ gate: string; passed: boolean; skipped?: boolean; detail?: Record<string, unknown> }>
    | undefined;
  if (!gates) return null;
  const failing = gates.filter((g) => !g.passed && !g.skipped);
  if (failing.length === 0) return null;
  return failing
    .map((g) => {
      const check = CHECK_LABEL[String(g.detail?.failed_check ?? "")];
      return check ? `${g.gate} · ${check}` : g.gate;
    })
    .join("  ·  ");
}

const ACTION_STYLE: Record<DecisionAction, { color: string; label: string }> = {
  EXECUTED: { color: "var(--verdigris)", label: "filled" },
  REFUSED: { color: "var(--oxide)", label: "refused" },
  ABSTAINED: { color: "var(--line)", label: "abstained" },
};

type Group =
  | { kind: "single"; entry: Decision }
  | { kind: "run"; first: Decision; rest: Decision[]; key: string };

/**
 * The template of a reason: the sentence with its particulars removed.
 *
 * "Max loss $310 fits the tier 0 budget…" and "Max loss $412 fits the tier 0
 * budget…" are the SAME decision made about different numbers, and eight of
 * them in a row teach nothing seven times. Numbers, tickers and dates are
 * masked; a genuinely different sentence — a different failing gate, a
 * different rule — never matches and always renders in full.
 */
function reasonTemplate(reason: string): string {
  return reason
    .replace(/[A-Z][A-Z.]{1,5}/g, "#") // tickers (and stray acronyms — fine)
    .replace(/[−-]?\$?\d[\d,]*(\.\d+)?%?/g, "#") // dollars, counts, percentages
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Consecutive entries with the same (outcome, reason template) collapse: the
 * first renders IN FULL, the rest fold into "+N more, same reason". Fills
 * never collapse, whatever their text.
 */
function groupDecisions(decisions: Decision[]): Group[] {
  const groups: Group[] = [];
  let run: Decision[] = [];
  let runKey: string | null = null;

  const flush = () => {
    if (run.length >= 2) {
      groups.push({ kind: "run", first: run[0]!, rest: run.slice(1), key: run[0]!.id });
    } else {
      run.forEach((entry) => groups.push({ kind: "single", entry }));
    }
    run = [];
    runKey = null;
  };

  for (const decision of decisions) {
    if (decision.action === "EXECUTED") {
      flush();
      groups.push({ kind: "single", entry: decision });
      continue;
    }
    const key = `${decision.action}|${reasonTemplate(decision.reason)}`;
    if (key !== runKey) flush();
    runKey = key;
    run.push(decision);
  }
  flush();
  return groups;
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
  const gateLine = failingGateLine(decision);
  const filled = decision.action === "EXECUTED";
  return (
    <li
      className={`border-t border-[color:var(--line)] first:border-t-0 ${
        isNewest ? "audit-enter" : ""
      }`}
    >
      {/* The whole entry links to its decision trace — conclusions here,
          reasoning one click deeper. Cursor, hover raise and the trailing
          TRACE glyph all say so; nothing here is decoration. */}
      <Link
        href={`/trace/${decision.id}`}
        className="t-fast group block cursor-pointer px-1 py-2 hover:bg-[color:var(--panel-alt)]"
        aria-label={`Open the decision trace for ${decision.symbol ?? "this decision"}`}
      >
        {/* line 1 — time, outcome, symbol, affordance */}
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
          <span
            className="mono ml-auto shrink-0 text-[9px] tracking-wider text-[color:var(--text-faint)] group-hover:text-[color:var(--brass)] group-focus-visible:text-[color:var(--brass)]"
            aria-hidden
          >
            TRACE →
          </span>
        </div>
        {/* line 2 — the failing gate, the scannable key */}
        {gateLine && (
          <p className="mono mt-0.5 text-[10px] lowercase tracking-wide text-[color:var(--text)]">
            {gateLine}
          </p>
        )}
        {/* line 3 — the reason, two lines max. Full text lives on the trace.
            Fills are the product's rarest output and never truncate. */}
        <p
          className={`mt-0.5 text-[11px] leading-snug text-[color:var(--text)]${
            filled ? "" : " line-clamp-2"
          }`}
        >
          {stripPromotionTail(decision.reason)}
        </p>
        {decision.model_rationale && filled && (
          <p className="mt-1 border-l border-[color:var(--line)] pl-2 text-[10px] italic leading-snug text-[color:var(--text-dim)]">
            {decision.model_rationale}
          </p>
        )}
      </Link>
    </li>
  );
}

function Run({ first, rest, isNewest }: { first: Decision; rest: Decision[]; isNewest: boolean }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      {/* The first of the run renders in full — a refusal's reason is the
          product, and it appears once at full strength rather than N times. */}
      <FullEntry decision={first} isNewest={isNewest} />
      <li className="py-1 pl-5">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="t-fast mono flex items-center gap-2 text-[10px] text-[color:var(--text-dim)] hover:text-[color:var(--text)]"
        >
          <span
            className="border border-[color:var(--line)] px-1 text-[9px]"
            style={{ borderRadius: "var(--radius)" }}
          >
            {open ? "−" : `+${rest.length}`}
          </span>
          {open ? "collapse" : `${rest.length} more, same reason`}
        </button>
        {open && (
          <ul className="mt-1 border-l border-[color:var(--line)] pl-2">
            {rest.map((entry) => (
              <li key={entry.id} className="py-1">
                <Link
                  href={`/trace/${entry.id}`}
                  className="t-fast block hover:bg-[color:var(--panel)]"
                >
                  <p className="mono text-[10px] text-[color:var(--text-dim)]">
                    {clockTime(entry.ts)} · {entry.symbol ?? "—"}
                  </p>
                  <p className="line-clamp-2 text-[11px] leading-snug text-[color:var(--text)]">
                    {stripPromotionTail(entry.reason)}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </li>
    </>
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
      <p className="mb-2 text-[10px] leading-snug text-[color:var(--text-dim)]">
        every decision is traceable — click any entry
      </p>

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
              <Run key={group.key} first={group.first} rest={group.rest} isNewest={i === 0} />
            ),
          )}
        </ul>
      )}
    </section>
  );
}
