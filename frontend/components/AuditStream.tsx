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
  EXECUTED: { color: "var(--positive)", label: "Filled" },
  REFUSED: { color: "var(--negative)", label: "Refused" },
  ABSTAINED: { color: "var(--text-faint)", label: "Abstained" },
  CONFIG: { color: "var(--accent)", label: "Config" },
};

/** Outcome as a small tinted badge — scannable at a glance, readable ink. */
function Badge({ action }: { action: DecisionAction }) {
  const style = ACTION_STYLE[action] ?? ACTION_STYLE.ABSTAINED;
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[11px] font-bold uppercase tracking-[0.06em]"
      style={{
        color: action === "ABSTAINED" ? "var(--text-dim)" : style.color,
        background: `color-mix(in srgb, ${style.color} 12%, transparent)`,
      }}
    >
      {style.label}
    </span>
  );
}

type Group =
  | { kind: "single"; entry: Decision }
  | { kind: "config"; entry: Decision }
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
 * Entries with the same (outcome, reason template) collapse into one run: the
 * first renders IN FULL, the rest fold into "+N more, same reason". Runs are
 * bounded by FILLS, not by strict adjacency — the desk's cycles interleave
 * refusals with abstentions, so strictly-consecutive runs break every two or
 * three rows and a full book still reads as a wall of identical capacity
 * refusals. A fill is a barrier: nothing groups across one, so the rare
 * executions stay honest chronological anchors. Fills never collapse.
 */
function groupDecisions(decisions: Decision[]): Group[] {
  const groups: Group[] = [];
  const open = new Map<string, Extract<Group, { kind: "run" }>>();

  for (const decision of decisions) {
    if (decision.action === "CONFIG") {
      // An era divider: the configuration changed here, and reasoning on the
      // two sides cites different standing parameters. Nothing groups across.
      open.clear();
      groups.push({ kind: "config", entry: decision });
      continue;
    }
    if (decision.action === "EXECUTED") {
      open.clear(); // barrier: a fill ends every open run
      groups.push({ kind: "single", entry: decision });
      continue;
    }
    const key = `${decision.action}|${reasonTemplate(decision.reason)}`;
    const run = open.get(key);
    if (run) {
      run.rest.push(decision);
    } else {
      const fresh: Extract<Group, { kind: "run" }> = {
        kind: "run",
        first: decision,
        rest: [],
        key: decision.id,
      };
      open.set(key, fresh);
      groups.push(fresh);
    }
  }
  // A run of one is just a single entry.
  return groups.map((group) =>
    group.kind === "run" && group.rest.length === 0
      ? { kind: "single" as const, entry: group.first }
      : group,
  );
}

function FullEntry({ decision, isNewest }: { decision: Decision; isNewest: boolean }) {
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
        className="t-fast group block cursor-pointer rounded-lg px-2 py-3 hover:bg-[color:var(--panel-alt)]"
        aria-label={`Open the decision trace for ${decision.symbol ?? "this decision"}`}
      >
        {/* line 1 — outcome badge, symbol, time, trace affordance */}
        <div className="flex items-center gap-2.5">
          <Badge action={decision.action} />
          {decision.symbol && (
            <span className="shrink-0 text-[14px] font-bold tracking-tight text-[color:var(--text)]">
              {decision.symbol}
            </span>
          )}
          <span
            className="ml-auto shrink-0 text-[12px] font-semibold text-[color:var(--text-faint)] group-hover:text-[color:var(--accent)] group-focus-visible:text-[color:var(--accent)]"
            aria-hidden
          >
            Trace →
          </span>
          <time
            className="mono shrink-0 text-[12px] text-[color:var(--text-faint)]"
            dateTime={decision.ts}
            title={timeAgo(decision.ts)}
          >
            {clockTime(decision.ts)}
          </time>
        </div>
        {/* line 2 — the failing gate, the scannable key */}
        {gateLine && (
          <p className="mono mt-0.5 text-[12px] lowercase tracking-wide text-[color:var(--text)]">
            {gateLine}
          </p>
        )}
        {/* line 3 — the reason, two lines max. Full text lives on the trace.
            Fills are the product's rarest output and never truncate. */}
        <p
          className={`mt-0.5 text-[13px] leading-snug text-[color:var(--text)]${
            filled ? "" : " line-clamp-2"
          }`}
        >
          {stripPromotionTail(decision.reason)}
        </p>
        {decision.model_rationale && filled && (
          <p className="mt-1 border-l border-[color:var(--line)] pl-2 text-[12px] italic leading-snug text-[color:var(--text-dim)]">
            {decision.model_rationale}
          </p>
        )}
      </Link>
    </li>
  );
}

function ConfigDivider({ decision }: { decision: Decision }) {
  return (
    <li className="py-2" aria-label="Configuration change">
      <div className="flex items-center gap-2">
        <span className="h-px flex-1 bg-[color:var(--accent)] opacity-40" aria-hidden />
        <span
          className="mono shrink-0 rounded-full px-2 py-0.5 text-[11px] font-bold uppercase tracking-[0.06em]"
          style={{
            color: "var(--accent)",
            background: "color-mix(in srgb, var(--accent) 12%, transparent)",
          }}
        >
          config
        </span>
        <time className="mono shrink-0 text-[12px] text-[color:var(--text-faint)]" dateTime={decision.ts}>
          {clockTime(decision.ts)}
        </time>
        <span className="h-px flex-1 bg-[color:var(--accent)] opacity-40" aria-hidden />
      </div>
      <p className="mt-1 text-center text-[12px] leading-snug text-[color:var(--text-dim)]">
        {decision.reason}
      </p>
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
          className="t-fast mono flex items-center gap-2 text-[12px] text-[color:var(--text-dim)] hover:text-[color:var(--text)]"
        >
          <span
            className="border border-[color:var(--line)] px-1 text-[12px]"
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
                  <p className="mono text-[12px] text-[color:var(--text-dim)]">
                    {clockTime(entry.ts)} · {entry.symbol ?? "—"}
                  </p>
                  <p className="line-clamp-2 text-[13px] leading-snug text-[color:var(--text)]">
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

type Filter = "ALL" | DecisionAction;

export function AuditStream({ decisions, counts }: Props) {
  const [filter, setFilter] = useState<Filter>("ALL");
  const filtered = useMemo(
    () => (filter === "ALL" ? decisions : decisions.filter((d) => d.action === filter)),
    [decisions, filter],
  );
  const groups = useMemo(() => groupDecisions(filtered), [filtered]);

  const chips: Array<{ key: Filter; label: string; count?: number }> = [
    { key: "ALL", label: "All" },
    { key: "EXECUTED", label: "Filled", count: counts?.EXECUTED },
    { key: "REFUSED", label: "Refused", count: counts?.REFUSED },
    { key: "ABSTAINED", label: "Abstained", count: counts?.ABSTAINED },
  ];

  return (
    <section className="flex flex-col p-4 lg:h-full lg:min-h-0 lg:flex-1" aria-label="Decision stream">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="whitespace-nowrap text-[16px] font-bold tracking-tight text-[color:var(--text)]">
          Audit log
        </h2>
        {/* The way into the evidence — a judge reading the rail should see it
            without scrolling. */}
        <Link
          href="/audit"
          className="t-fast mono whitespace-nowrap text-[12px] uppercase tracking-wider text-[color:var(--text-dim)] hover:text-[color:var(--brass)]"
        >
          full record →
        </Link>
      </div>
      <p className="mt-0.5 text-[13px] leading-snug text-[color:var(--text-dim)]">
        Every decision is traceable — click any entry. Counts are all-time; the
        strip above counts this session only.
      </p>
      <div className="mb-3 mt-2.5 flex flex-wrap gap-1.5" role="group" aria-label="Filter decisions">
        {chips.map((chip) => {
          const active = filter === chip.key;
          return (
            <button
              key={chip.key}
              type="button"
              onClick={() => setFilter(chip.key)}
              aria-pressed={active}
              className="t-fast rounded-full border px-2.5 py-1 text-[12px] font-semibold"
              style={{
                borderColor: active ? "var(--accent)" : "var(--line)",
                background: active
                  ? "color-mix(in srgb, var(--accent) 14%, transparent)"
                  : "transparent",
                color: active ? "var(--text)" : "var(--text-dim)",
              }}
            >
              {chip.label}
              {chip.count !== undefined && (
                <span className="mono ml-1 text-[11px] text-[color:var(--text-faint)]">
                  {chip.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {groups.length === 0 ? (
        <p className="text-[13px] text-[color:var(--text-dim)]">
          {filter === "ALL"
            ? "No decisions yet. The desk logs every refusal and abstention here, not only the trades it takes."
            : "Nothing with this outcome in the loaded window."}
        </p>
      ) : (
        // The list must LOOK scrollable: a persistent scrollbar plus a fade at
        // the bottom edge saying "there is more below" — nobody should have to
        // guess that the log continues.
        <div className="relative lg:min-h-0 lg:flex-1">
          <ul className="pr-2 lg:h-full lg:overflow-y-auto">
            {groups.map((group, i) =>
              group.kind === "single" ? (
                <FullEntry key={group.entry.id} decision={group.entry} isNewest={i === 0} />
              ) : group.kind === "config" ? (
                <ConfigDivider key={group.entry.id} decision={group.entry} />
              ) : (
                <Run key={group.key} first={group.first} rest={group.rest} isNewest={i === 0} />
              ),
            )}
            <li className="py-3 text-center">
              <Link
                href="/audit"
                className="t-fast mono text-[12px] text-[color:var(--text-dim)] hover:text-[color:var(--brass)]"
              >
                {counts?.TOTAL
                  ? `See all ${counts.TOTAL.toLocaleString("en-US")} decisions →`
                  : "See the full record →"}
              </Link>
            </li>
          </ul>
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 bottom-0 hidden h-14 lg:block"
            style={{ background: "linear-gradient(to bottom, transparent, var(--ground))" }}
          />
        </div>
      )}
    </section>
  );
}
