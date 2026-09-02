"use client";

/**
 * /audit — the full decision record.
 *
 * The desk rail is a live stream; this is the evidence. Every decision the
 * desk ever made on this account, filterable, searchable, linkable — the
 * query string IS the page state, so any filtered view can be sent as a URL.
 *
 * Runs of identical reasoning (same outcome, same reason template) collapse
 * into one row with a count and a time range. Fills never collapse and bound
 * every run — nothing groups across an execution. The summary panel is
 * computed from the current filter, so it always describes exactly what the
 * table shows.
 */

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { Header } from "@/components/Header";
import { API_BASE, useAuditQuery, useStatus } from "@/lib/api";
import { clockTime, structureLabel } from "@/lib/format";
import type { AuditItem, AuditLite, AuditRun, DecisionAction } from "@/lib/types";

const PAGE_SIZE = 100;
const GATES = ["liquidity", "earnings", "term", "stress", "budget"] as const;

const ACTION_STYLE: Record<DecisionAction, { color: string; label: string }> = {
  EXECUTED: { color: "var(--positive)", label: "Filled" },
  REFUSED: { color: "var(--negative)", label: "Refused" },
  ABSTAINED: { color: "var(--text-faint)", label: "Abstained" },
};

function Badge({ action }: { action: DecisionAction }) {
  const style = ACTION_STYLE[action] ?? ACTION_STYLE.ABSTAINED;
  return (
    <span
      className="whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-bold uppercase tracking-[0.06em]"
      style={{
        color: action === "ABSTAINED" ? "var(--text-dim)" : style.color,
        background: `color-mix(in srgb, ${style.color} 12%, transparent)`,
      }}
    >
      {style.label}
    </span>
  );
}

/** "01 Sep 19:57" — the record spans days, so the clock alone is not enough. */
function dayTime(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function dayOnly(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

// ------------------------------------------------------------------ URL state

interface Filters {
  action: string;
  symbols: string[];
  gate: string;
  q: string;
  from: string;
  to: string;
  sort: string;
  grouped: boolean;
  offset: number;
}

function readFilters(params: URLSearchParams): Filters {
  return {
    action: params.get("action") ?? "",
    symbols: (params.get("symbols") ?? "").split(",").filter(Boolean),
    gate: params.get("gate") ?? "",
    q: params.get("q") ?? "",
    from: params.get("from") ?? "",
    to: params.get("to") ?? "",
    sort: params.get("sort") ?? "desc",
    grouped: params.get("grouped") !== "0",
    offset: Math.max(0, Number(params.get("offset") ?? 0) || 0),
  };
}

function toQueryString(f: Filters, forExport = false): string {
  const qs = new URLSearchParams();
  if (f.action) qs.set("action", f.action);
  if (f.symbols.length) qs.set("symbols", f.symbols.join(","));
  if (f.gate) qs.set("gate", f.gate);
  if (f.q) qs.set("q", f.q);
  if (f.from) qs.set("date_from", f.from);
  if (f.to) qs.set("date_to", f.to);
  if (f.sort !== "desc") qs.set("sort", f.sort);
  if (!forExport) {
    if (!f.grouped) qs.set("grouped", "0");
    if (f.offset) qs.set("offset", String(f.offset));
    qs.set("limit", String(PAGE_SIZE));
  }
  return qs.toString();
}

/** The address-bar form uses the short param names the page owns. */
function toUrlString(f: Filters): string {
  const qs = new URLSearchParams();
  if (f.action) qs.set("action", f.action);
  if (f.symbols.length) qs.set("symbols", f.symbols.join(","));
  if (f.gate) qs.set("gate", f.gate);
  if (f.q) qs.set("q", f.q);
  if (f.from) qs.set("from", f.from);
  if (f.to) qs.set("to", f.to);
  if (f.sort !== "desc") qs.set("sort", f.sort);
  if (!f.grouped) qs.set("grouped", "0");
  if (f.offset) qs.set("offset", String(f.offset));
  return qs.toString();
}

/** API param names differ from the short URL ones for the dates. */
function apiQueryString(params: URLSearchParams): string {
  return toQueryString(readFilters(params));
}

// ------------------------------------------------------------------ controls

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className="t-fast rounded-full border px-2.5 py-1 text-[12px] font-semibold"
      style={{
        borderColor: active ? "var(--accent)" : "var(--line)",
        background: active ? "color-mix(in srgb, var(--accent) 14%, transparent)" : "transparent",
        color: active ? "var(--text)" : "var(--text-dim)",
      }}
    >
      {children}
    </button>
  );
}

// ------------------------------------------------------------------ summary

function GateBars({ byGate }: { byGate: Array<{ gate: string; count: number }> }) {
  const max = Math.max(...byGate.map((g) => g.count), 1);
  if (byGate.length === 0)
    return (
      <p className="text-[13px] text-[color:var(--text-dim)]">
        No refusals in the current filter.
      </p>
    );
  return (
    <ul className="space-y-1.5">
      {byGate.map(({ gate, count }) => (
        <li key={gate} className="flex items-center gap-2">
          <span className="mono w-20 shrink-0 text-[12px] text-[color:var(--text-dim)]">
            {gate}
          </span>
          <span className="relative h-2 flex-1 overflow-hidden rounded-full bg-[color:var(--panel-alt)]">
            <span
              className="absolute inset-y-0 left-0 rounded-full"
              style={{ width: `${(count / max) * 100}%`, background: "var(--accent)" }}
            />
          </span>
          <span className="mono w-12 shrink-0 text-right text-[12px] text-[color:var(--text)]">
            {count.toLocaleString("en-US")}
          </span>
        </li>
      ))}
    </ul>
  );
}

function PerDaySpark({ perDay }: { perDay: Array<{ date: string; count: number }> }) {
  if (perDay.length < 2)
    return (
      <p className="mono text-[12px] text-[color:var(--text-dim)]">
        {perDay.length === 1
          ? `${perDay[0]!.count.toLocaleString("en-US")} decisions on ${dayOnly(perDay[0]!.date)}`
          : "—"}
      </p>
    );
  const max = Math.max(...perDay.map((d) => d.count), 1);
  const W = 220;
  const H = 40;
  const pts = perDay
    .map((d, i) => {
      const x = 2 + (i / (perDay.length - 1)) * (W - 4);
      const y = H - 3 - (d.count / max) * (H - 8);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} aria-hidden>
        <polyline points={pts} fill="none" stroke="var(--accent)" strokeWidth={1.5} />
      </svg>
      <p className="mono mt-1 flex justify-between text-[11px] text-[color:var(--text-faint)]">
        <span>{dayOnly(perDay[0]!.date)}</span>
        <span>peak {max.toLocaleString("en-US")}/day</span>
        <span>{dayOnly(perDay[perDay.length - 1]!.date)}</span>
      </p>
    </div>
  );
}

// ------------------------------------------------------------------ rows

function gateLine(lite: AuditLite): string | null {
  return lite.gates.length > 0 ? lite.gates.join(" · ") : null;
}

function DecisionCells({ lite }: { lite: AuditLite }) {
  return (
    <>
      <td className="mono whitespace-nowrap px-3 py-2 text-[12px] text-[color:var(--text-dim)]">
        {dayTime(lite.ts)}
      </td>
      <td className="px-3 py-2">
        <Badge action={lite.action} />
      </td>
      <td className="mono px-3 py-2 text-[13px] font-bold">{lite.symbol ?? "—"}</td>
      <td className="whitespace-nowrap px-3 py-2 text-[13px]">
        {lite.kind ? structureLabel(lite.kind) : "—"}
      </td>
      <td className="mono px-3 py-2 text-[12px] lowercase text-[color:var(--text)]">
        {gateLine(lite) ?? "—"}
      </td>
      <td className="max-w-[28rem] px-3 py-2">
        <span className="block truncate text-[13px] text-[color:var(--text)]" title={lite.reason}>
          {lite.reason}
        </span>
      </td>
    </>
  );
}

function DecisionRow({ lite }: { lite: AuditLite }) {
  const router = useRouter();
  const open = () => router.push(`/trace/${lite.id}`);
  return (
    <tr
      tabIndex={0}
      onClick={open}
      onKeyDown={(e) => {
        if (e.key === "Enter") open();
      }}
      className="t-fast cursor-pointer border-b border-[color:var(--line)] last:border-0 hover:bg-[color:var(--panel-alt)] focus-visible:bg-[color:var(--panel-alt)] focus-visible:outline-none"
      aria-label={`Open the decision trace for ${lite.symbol ?? "this decision"}`}
    >
      <DecisionCells lite={lite} />
      <td className="mono whitespace-nowrap px-3 py-2 text-right text-[12px] font-semibold text-[color:var(--text-faint)]">
        Trace →
      </td>
    </tr>
  );
}

/** A collapsed run. Expanding fetches its members from the same endpoint,
 *  pinned to the run's template and time range. */
function RunRow({ run, filters }: { run: AuditRun; filters: Filters }) {
  const [open, setOpen] = useState(false);
  const [members, setMembers] = useState<AuditLite[] | null>(null);
  const [loading, setLoading] = useState(false);

  const expand = async () => {
    setOpen((v) => !v);
    if (members || loading) return;
    setLoading(true);
    try {
      const qs = new URLSearchParams({
        action: run.action,
        template: run.template,
        date_from: run.first_ts,
        date_to: run.last_ts,
        grouped: "0",
        sort: filters.sort,
        limit: "500",
      });
      if (filters.symbols.length) qs.set("symbols", filters.symbols.join(","));
      if (filters.gate) qs.set("gate", filters.gate);
      if (filters.q) qs.set("q", filters.q);
      const res = await fetch(`${API_BASE}/api/audit/query?${qs}`);
      const body = (await res.json()) as { items: AuditItem[] };
      setMembers(body.items.filter((i): i is { type: "decision" } & AuditLite => i.type === "decision"));
    } catch {
      setMembers([]);
    } finally {
      setLoading(false);
    }
  };

  const span =
    run.first_ts.slice(0, 10) === run.last_ts.slice(0, 10)
      ? `${dayOnly(run.first_ts)} ${clockTime(run.first_ts)}–${clockTime(run.last_ts)}`
      : `${dayOnly(run.first_ts)} – ${dayOnly(run.last_ts)}`;

  return (
    <>
      <tr
        tabIndex={0}
        onClick={expand}
        onKeyDown={(e) => {
          if (e.key === "Enter") void expand();
        }}
        aria-expanded={open}
        className="t-fast cursor-pointer border-b border-[color:var(--line)] last:border-0 hover:bg-[color:var(--panel-alt)] focus-visible:bg-[color:var(--panel-alt)] focus-visible:outline-none"
      >
        <td className="mono whitespace-nowrap px-3 py-2 text-[12px] text-[color:var(--text-dim)]">
          {span}
        </td>
        <td className="px-3 py-2">
          <span className="flex items-center gap-1.5">
            <Badge action={run.action} />
            <span
              className="mono rounded-full border border-[color:var(--line)] px-1.5 text-[11px] text-[color:var(--text-dim)]"
              title={`${run.count} decisions with this outcome and reasoning`}
            >
              ×{run.count.toLocaleString("en-US")}
            </span>
          </span>
        </td>
        <td className="mono px-3 py-2 text-[12px] text-[color:var(--text-dim)]">
          {run.symbols.length > 3
            ? `${run.symbols.slice(0, 3).join(" ")} +${run.symbols.length - 3}`
            : run.symbols.join(" ") || "—"}
        </td>
        <td className="whitespace-nowrap px-3 py-2 text-[13px]">
          {run.kinds.length === 1 ? structureLabel(run.kinds[0]!) : run.kinds.length > 1 ? "mixed" : "—"}
        </td>
        <td className="mono px-3 py-2 text-[12px] lowercase text-[color:var(--text)]">
          {run.gates.join(" · ") || "—"}
        </td>
        <td className="max-w-[28rem] px-3 py-2">
          <span
            className="block truncate text-[13px] text-[color:var(--text)]"
            title={run.sample.reason}
          >
            {run.sample.reason}
          </span>
        </td>
        <td className="mono whitespace-nowrap px-3 py-2 text-right text-[12px] font-semibold text-[color:var(--text-faint)]">
          {open ? "collapse −" : "expand +"}
        </td>
      </tr>
      {open && (
        <tr className="border-b border-[color:var(--line)]">
          <td colSpan={7} className="bg-[color:var(--panel-alt)] px-3 py-1">
            {loading && (
              <p className="py-2 text-[13px] text-[color:var(--text-dim)]">Loading the run…</p>
            )}
            {members && members.length === 0 && !loading && (
              <p className="py-2 text-[13px] text-[color:var(--text-dim)]">
                Could not load this run&apos;s members — the trace links above still work.
              </p>
            )}
            {members && members.length > 0 && (
              <table className="w-full border-collapse">
                <tbody>
                  {members.map((m) => (
                    <DecisionRow key={m.id} lite={m} />
                  ))}
                </tbody>
              </table>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

// ------------------------------------------------------------------ the page

function AuditPageInner() {
  const router = useRouter();
  const params = useSearchParams();
  const filters = useMemo(() => readFilters(new URLSearchParams(params.toString())), [params]);

  const { data: status } = useStatus();
  const { data, isLoading } = useAuditQuery(apiQueryString(new URLSearchParams(params.toString())));

  // The search box debounces before it touches the URL.
  const [searchDraft, setSearchDraft] = useState(filters.q);
  useEffect(() => setSearchDraft(filters.q), [filters.q]);
  useEffect(() => {
    if (searchDraft === filters.q) return;
    const t = setTimeout(() => update({ q: searchDraft, offset: 0 }), 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchDraft]);

  const update = (patch: Partial<Filters>) => {
    const next = { ...filters, ...patch };
    const qs = toUrlString(next);
    router.replace(qs ? `/audit?${qs}` : "/audit", { scroll: false });
  };

  const activeFilterNames = [
    filters.action && `outcome: ${ACTION_STYLE[filters.action as DecisionAction]?.label ?? filters.action}`,
    filters.symbols.length > 0 && `symbols: ${filters.symbols.join(", ")}`,
    filters.gate && `gate: ${filters.gate}`,
    filters.q && `search: “${filters.q}”`,
    (filters.from || filters.to) && `date range`,
  ].filter(Boolean) as string[];

  const totals = data?.totals;
  const exportHref = `${API_BASE}/api/audit/export.csv?${toQueryString(filters, true)}`;
  const pageFrom = data ? Math.min(data.offset + 1, data.total_items) : 0;
  const pageTo = data ? Math.min(data.offset + data.items.length, data.total_items) : 0;

  return (
    <div className="flex min-h-screen flex-col">
      <Header status={status} tab="audit" />

      <main className="mx-auto w-full max-w-6xl flex-1 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-4">
          <h1 className="font-display text-[length:var(--fs-md)]">Decision record</h1>
          <a
            href={exportHref}
            download
            className="t-fast mono text-[12px] uppercase tracking-wider text-[color:var(--text-dim)] hover:text-[color:var(--text)]"
          >
            download csv ↓
          </a>
        </div>

        {/* header strip — all-time for this account */}
        <p className="mono mt-2 text-[13px] text-[color:var(--text-dim)]">
          {totals ? (
            <>
              {totals.TOTAL?.toLocaleString("en-US")} decisions ·{" "}
              <span style={{ color: "var(--positive)" }}>
                {totals.EXECUTED?.toLocaleString("en-US")} filled
              </span>{" "}
              ·{" "}
              <span style={{ color: "var(--negative)" }}>
                {totals.REFUSED?.toLocaleString("en-US")} refused
              </span>{" "}
              · {totals.ABSTAINED?.toLocaleString("en-US")} abstained
              {data?.range.first && data?.range.last && (
                <>
                  {" "}
                  · {dayOnly(data.range.first)} – {dayOnly(data.range.last)}
                </>
              )}
              {data?.account_suffix && ` · account ••••${data.account_suffix}`}
            </>
          ) : (
            "loading the record…"
          )}
        </p>
        <p className="mt-1 text-[13px] text-[color:var(--text-dim)]">
          Every decision this account&apos;s desk ever made — refusals and abstentions as
          prominent as fills. Counts are all-time; any filtered view is linkable by URL.
        </p>

        {/* controls */}
        <div className="mt-4 flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter the record">
          {(
            [
              ["", "All"],
              ["EXECUTED", "Filled"],
              ["REFUSED", "Refused"],
              ["ABSTAINED", "Abstained"],
            ] as const
          ).map(([value, label]) => (
            <Chip
              key={label}
              active={filters.action === value}
              onClick={() => update({ action: value, offset: 0 })}
            >
              {label}
            </Chip>
          ))}
          <span className="mx-1 h-4 w-px bg-[color:var(--line)]" aria-hidden />
          {GATES.map((gate) => (
            <Chip
              key={gate}
              active={filters.gate === gate}
              onClick={() => update({ gate: filters.gate === gate ? "" : gate, offset: 0 })}
            >
              {gate}
            </Chip>
          ))}
        </div>

        {(data?.symbols_seen?.length ?? 0) > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter by symbol">
            {data!.symbols_seen.map((symbol) => (
              <Chip
                key={symbol}
                active={filters.symbols.includes(symbol)}
                onClick={() =>
                  update({
                    symbols: filters.symbols.includes(symbol)
                      ? filters.symbols.filter((s) => s !== symbol)
                      : [...filters.symbols, symbol],
                    offset: 0,
                  })
                }
              >
                {symbol}
              </Chip>
            ))}
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            type="search"
            value={searchDraft}
            onChange={(e) => setSearchDraft(e.target.value)}
            placeholder="search reasons…"
            aria-label="Search reason text"
            className="mono w-56 rounded-lg border border-[color:var(--line)] bg-transparent px-2.5 py-1.5 text-[13px] text-[color:var(--text)] placeholder:text-[color:var(--text-faint)] focus:border-[color:var(--accent)] focus:outline-none"
          />
          <label className="mono flex items-center gap-1.5 text-[12px] text-[color:var(--text-dim)]">
            from
            <input
              type="date"
              value={filters.from}
              onChange={(e) => update({ from: e.target.value, offset: 0 })}
              className="rounded-lg border border-[color:var(--line)] bg-transparent px-2 py-1 text-[12px] text-[color:var(--text)]"
            />
          </label>
          <label className="mono flex items-center gap-1.5 text-[12px] text-[color:var(--text-dim)]">
            to
            <input
              type="date"
              value={filters.to}
              onChange={(e) => update({ to: e.target.value, offset: 0 })}
              className="rounded-lg border border-[color:var(--line)] bg-transparent px-2 py-1 text-[12px] text-[color:var(--text)]"
            />
          </label>
          <Chip
            active={filters.sort === "asc"}
            onClick={() => update({ sort: filters.sort === "asc" ? "desc" : "asc", offset: 0 })}
          >
            {filters.sort === "asc" ? "oldest first" : "newest first"}
          </Chip>
          <Chip active={!filters.grouped} onClick={() => update({ grouped: !filters.grouped, offset: 0 })}>
            {filters.grouped ? "grouped" : "expanded"}
          </Chip>
        </div>

        {/* summary panel — computed from the current filter */}
        {data && data.summary.count > 0 && (
          <section
            className="panel mt-4 grid gap-6 p-4 md:grid-cols-3"
            aria-label="Summary of the filtered view"
          >
            <div>
              <h2 className="mono mb-2 text-[12px] uppercase tracking-wider text-[color:var(--text-dim)]">
                refusals by gate
              </h2>
              <GateBars byGate={data.summary.by_gate} />
            </div>
            <div>
              <h2 className="mono mb-2 text-[12px] uppercase tracking-wider text-[color:var(--text-dim)]">
                decisions per day
              </h2>
              <PerDaySpark perDay={data.summary.per_day} />
            </div>
            <div>
              <h2 className="mono mb-2 text-[12px] uppercase tracking-wider text-[color:var(--text-dim)]">
                this view
              </h2>
              <p className="text-[14px] leading-relaxed text-[color:var(--text)]">
                {data.summary.count.toLocaleString("en-US")} decisions —{" "}
                {data.summary.executed.toLocaleString("en-US")} filled,{" "}
                {data.summary.refused.toLocaleString("en-US")} refused,{" "}
                {data.summary.abstained.toLocaleString("en-US")} abstained.
                {data.summary.top_refused && (
                  <>
                    {" "}
                    Most refused:{" "}
                    <span className="mono font-bold">{data.summary.top_refused.symbol}</span> (
                    {data.summary.top_refused.count.toLocaleString("en-US")}).
                  </>
                )}
              </p>
            </div>
          </section>
        )}

        {/* the table */}
        {data && data.items.length === 0 ? (
          <div className="panel mt-4 p-6">
            <p className="text-[14px] text-[color:var(--text)]">
              {isLoading ? "Loading the record…" : "Nothing matches the current filter."}
            </p>
            {!isLoading && activeFilterNames.length > 0 && (
              <p className="mt-1 text-[13px] text-[color:var(--text-dim)]">
                Active filters: {activeFilterNames.join(" · ")} — remove one to widen the view.
              </p>
            )}
            {!isLoading && activeFilterNames.length === 0 && (
              <p className="mt-1 text-[13px] text-[color:var(--text-dim)]">
                No decisions recorded yet. The desk logs every refusal and abstention here, not
                only the trades it takes.
              </p>
            )}
          </div>
        ) : (
          <div className="panel mt-4 overflow-x-auto">
            <table className="w-full min-w-[56rem] border-collapse text-left">
              <thead>
                <tr className="border-b border-[color:var(--line)]">
                  {["time", "outcome", "symbol", "structure", "failing gate", "reason", ""].map(
                    (h, i) => (
                      <th
                        key={i}
                        scope="col"
                        className="mono px-3 py-2 text-[12px] font-medium uppercase tracking-wider text-[color:var(--text-dim)]"
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {(data?.items ?? []).map((item: AuditItem) =>
                  item.type === "run" ? (
                    <RunRow key={`${item.template}-${item.first_ts}`} run={item} filters={filters} />
                  ) : (
                    <DecisionRow key={item.id} lite={item} />
                  ),
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* pagination */}
        {data && data.total_items > PAGE_SIZE && (
          <div className="mt-3 flex items-center justify-between">
            <button
              type="button"
              disabled={filters.offset === 0}
              onClick={() => update({ offset: Math.max(0, filters.offset - PAGE_SIZE) })}
              className="t-fast mono text-[12px] uppercase tracking-wider text-[color:var(--text-dim)] hover:text-[color:var(--text)] disabled:cursor-default disabled:opacity-40"
            >
              ← newer
            </button>
            <p className="mono text-[12px] text-[color:var(--text-faint)]">
              {pageFrom.toLocaleString("en-US")}–{pageTo.toLocaleString("en-US")} of{" "}
              {data.total_items.toLocaleString("en-US")} rows
              {filters.grouped && " (grouped)"}
            </p>
            <button
              type="button"
              disabled={pageTo >= data.total_items}
              onClick={() => update({ offset: filters.offset + PAGE_SIZE })}
              className="t-fast mono text-[12px] uppercase tracking-wider text-[color:var(--text-dim)] hover:text-[color:var(--text)] disabled:cursor-default disabled:opacity-40"
            >
              older →
            </button>
          </div>
        )}

        <p className="mono mt-6 max-w-2xl text-[12px] leading-relaxed text-[color:var(--text-dim)]">
          The log is append-only: no update path and no delete path exists anywhere in the
          codebase. Runs of identical reasoning collapse into one row; fills never collapse.
          Click any row for the full decision trace.
        </p>
      </main>
    </div>
  );
}

export default function AuditPage() {
  return (
    <Suspense fallback={<div className="min-h-screen" />}>
      <AuditPageInner />
    </Suspense>
  );
}
