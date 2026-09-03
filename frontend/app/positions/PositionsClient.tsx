"use client";

/**
 * Positions and P&L — deliberately the second screen.
 *
 * The product's claim is that risk governance matters more than returns, so the
 * landing view is the decision surface and this is behind a tab. That is a
 * design argument, not an oversight: leading with a P&L number over a few days
 * of paper trading would be leading with noise.
 *
 * Presentation rules, in the desk's own system: open positions read as cards
 * (a position is a thing you own, not a row), the closed record stays a table
 * (a record is a thing you scan). Every leg is labelled with its side and, on
 * credit structures, which leg is the protection — the defined-risk claim made
 * visible rather than asserted. No token, colour or component exists only here.
 */

import Link from "next/link";
import { useState } from "react";

import { Header } from "@/components/Header";
import { TierPips } from "@/components/RiskPanel";
import { contractLabel, dollars, money, structureLabel, timeAgo } from "@/lib/format";
import { useClosedPositions, usePositions, useRisk, useStatus } from "@/lib/api";
import type { Position, SystemStatus } from "@/lib/types";

/** Days held so far, from the real open timestamp. */
function daysHeld(position: Position): string {
  if (!position.opened_at) return "—";
  const days = (Date.now() - new Date(position.opened_at).getTime()) / 86_400_000;
  return days < 1 ? `${Math.max(1, Math.round(days * 24))}h` : `${days.toFixed(1)}d`;
}

/** Strike parsed from an OCC symbol, for ordering and side inference. */
function occStrike(symbol: string): number {
  const match = /(\d{8})$/.exec(symbol);
  return match ? Number(match[1]) / 1000 : 0;
}

/**
 * Which side each leg is on, derived from the structure kind and strikes.
 * Pure presentation: the sides are fixed by construction for every structure
 * the desk trades (the short leg of a put credit is the higher strike, of a
 * call credit the lower, condors short the inner strikes, debit spreads long
 * the nearer-the-money strike).
 */
function legSides(position: Position): Array<{ symbol: string; side: "SELL" | "BUY" }> {
  const legs = [...position.legs].sort((a, b) => occStrike(a) - occStrike(b));
  const kind = position.kind ?? "";
  // Short legs first, always: the obligation leads, the cap follows.
  const bySide = (short: Set<string>) =>
    legs
      .map((symbol) => ({
        symbol,
        side: (short.has(symbol) ? "SELL" : "BUY") as "SELL" | "BUY",
      }))
      .sort((a, b) => (a.side === b.side ? 0 : a.side === "SELL" ? -1 : 1));

  if (kind === "PUT_CREDIT" && legs.length === 2) return bySide(new Set([legs[1]!]));
  if (kind === "CALL_CREDIT" && legs.length === 2) return bySide(new Set([legs[0]!]));
  if (kind === "CALL_DEBIT" && legs.length === 2) return bySide(new Set([legs[1]!]));
  if (kind === "PUT_DEBIT" && legs.length === 2) return bySide(new Set([legs[0]!]));
  if (kind === "IRON_CONDOR" && legs.length === 4)
    return bySide(new Set([legs[1]!, legs[2]!]));
  return legs.map((symbol) => ({ symbol, side: "BUY" as const }));
}

/** What each leg IS, named on every leg so nothing reads as a missing field.
 *  Credit: the long wing caps the short leg — that is the protection. Debit:
 *  the long leg is the position itself and the short leg finances it; the
 *  debit paid is already the maximum loss, so no leg is "protection". */
function legLabel(position: Position, side: "SELL" | "BUY"): string {
  const credit = position.entry_credit > 0;
  if (credit) return side === "SELL" ? "short leg" : "long leg · protection";
  return side === "BUY" ? "long leg · the position" : "short leg · financing";
}

/**
 * The exit rules as chips, with the rule closest to firing carrying the
 * accent. Proximity is the displayed figures' own arithmetic — fraction of
 * the trigger already travelled — computed from nothing the page does not
 * already show.
 */
function exitChips(
  position: Position,
  status?: SystemStatus,
): Array<{ label: string; near: boolean; hint?: string }> {
  const rules = status?.exit_rules;
  if (!rules) {
    return ["profit target", "loss limit", "dte", "short-ITM defence"].map((label) => ({
      label,
      near: false,
    }));
  }
  const scores: Array<{ label: string; score: number; hint?: string }> = [];
  const tpPct = Math.round(rules.profit_target_pct * 100);
  if (position.entry_credit > 0) {
    const target = position.entry_credit * rules.profit_target_pct;
    const limit = position.entry_credit * rules.loss_limit_multiple;
    scores.push({
      label: `tp +${dollars(target, 0)} (${tpPct}%)`,
      score: target > 0 ? Math.max(0, position.unrealized_pnl / target) : 0,
    });
    scores.push({
      label: `sl −${dollars(limit, 0)} (${rules.loss_limit_multiple}x)`,
      score: limit > 0 ? Math.max(0, -position.unrealized_pnl / limit) : 0,
    });
  } else {
    // Debit vertical: max profit is width minus the debit paid — both already
    // on the card (strikes and entry). Same chip format as the credit side.
    const strikes = position.legs.map(occStrike).sort((a, b) => a - b);
    const width = (strikes[strikes.length - 1]! - strikes[0]!) * 100;
    const maxProfit = Math.max(0, width - Math.abs(position.entry_credit));
    const target = maxProfit * rules.profit_target_pct;
    scores.push({
      label: target > 0 ? `tp +${dollars(target, 0)} (${tpPct}%)` : `tp ${tpPct}% of max profit`,
      score: target > 0 ? Math.max(0, position.unrealized_pnl / target) : 0,
    });
    // No separate stop exists BY DESIGN: the debit paid is the maximum loss.
    // An absent chip reads as a gap; a stated reason reads as design.
    scores.push({
      label: "max loss is the debit",
      score: 0,
      hint: "A debit spread has no separate stop: the premium paid is the maximum loss, capped at entry.",
    });
  }
  scores.push({
    label: `dte ≤ ${rules.exit_dte_threshold}`,
    score: position.dte > 0 ? rules.exit_dte_threshold / position.dte : 1,
  });
  scores.push({ label: "short-ITM defence", score: 0 });

  const nearest = scores.reduce((a, b) => (b.score > a.score ? b : a));
  return scores.map(({ label, score, hint }) => ({
    label,
    near: score > 0 && label === nearest.label,
    hint,
  }));
}

/** Human wording for every close rule — the machine name never renders. */
const EXIT_LABEL: Record<string, string> = {
  profit_target: "Profit target",
  loss_limit: "Loss limit",
  dte: "DTE threshold",
  deadline: "Deadline",
  short_itm: "Assignment defence",
  duplicate_correction: "Duplicate correction",
  reconciled_closed_at_broker: "Closed at broker",
  breach: "Breach",
};

/** Symbols with a committed logo asset in /public/logos (fetched once from
 *  Parqet's asset service, served locally — no runtime dependency). Any
 *  symbol outside this set falls back to the monogram tile, so a future
 *  universe change never renders a broken image. */
const LOGO_SYMBOLS = new Set(["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMD", "TSLA"]);

/** The symbol mark: the real logo where an asset exists, otherwise a monogram
 *  tile in the app's accent. Always renders — never a broken image. */
function SymbolMark({ symbol, size = 30 }: { symbol: string; size?: number }) {
  const [failed, setFailed] = useState(false);
  if (LOGO_SYMBOLS.has(symbol) && !failed) {
    return (
      <img
        src={`/logos/${symbol}.jpg`}
        alt=""
        aria-hidden
        width={size}
        height={size}
        className="shrink-0 object-cover"
        style={{ borderRadius: "var(--radius)" }}
        onError={() => setFailed(true)}
      />
    );
  }
  return (
    <span
      aria-hidden
      className="mono inline-flex shrink-0 items-center justify-center font-bold"
      style={{
        width: size,
        height: size,
        borderRadius: "var(--radius)",
        background: "color-mix(in srgb, var(--accent) 14%, transparent)",
        color: "var(--accent)",
        fontSize: size * 0.4,
        letterSpacing: "-0.02em",
      }}
    >
      {symbol.slice(0, size >= 30 ? 4 : 3)}
    </span>
  );
}

/** One labelled figure of the header strip — the desk's label-over-value idiom. */
function Figure({ label, value, tone }: { label: string; value: React.ReactNode; tone?: string }) {
  return (
    <div>
      <p className="mono text-[12px] uppercase tracking-widest text-[color:var(--text-dim)]">
        {label}
      </p>
      <p
        className="mono mt-0.5 text-[17px] font-semibold tabular-nums"
        style={tone ? { color: tone } : undefined}
      >
        {value}
      </p>
    </div>
  );
}

function ExitChip({ label, near, hint }: { label: string; near: boolean; hint?: string }) {
  return (
    <span
      className="mono whitespace-nowrap rounded-full border px-2.5 py-1 text-[12px] font-semibold"
      style={{
        borderColor: near ? "var(--accent)" : "var(--line)",
        background: near ? "color-mix(in srgb, var(--accent) 14%, transparent)" : "transparent",
        color: near ? "var(--text)" : "var(--text-dim)",
      }}
      title={hint ?? (near ? "The rule currently closest to firing" : undefined)}
    >
      {label}
    </span>
  );
}

function PositionCard({ position, status }: { position: Position; status?: SystemStatus }) {
  const pnlColor = position.unrealized_pnl >= 0 ? "var(--verdigris)" : "var(--brass)";
  return (
    <article className="panel p-4">
      {/* header — symbol, structure, dte; unrealised carries the weight */}
      <div className="flex items-center gap-2.5">
        <SymbolMark symbol={position.symbol} />
        <div className="min-w-0">
          <p className="text-[15px] font-bold tracking-tight text-[color:var(--text)]">
            {position.symbol}
            <span className="font-normal text-[color:var(--text-dim)]">
              {" "}
              · {position.kind ? structureLabel(position.kind) : "—"} · {position.dte} DTE
            </span>
          </p>
        </div>
        <p
          className="mono ml-auto shrink-0 text-[19px] font-semibold tabular-nums"
          style={{ color: pnlColor }}
        >
          {money(position.unrealized_pnl)}
        </p>
      </div>

      {/* legs — the same side dots the candidate cards use; the long wing on a
          credit structure IS the defined risk, so it says so */}
      <ul className="mt-3 space-y-1 border-t border-[color:var(--line)] pt-3">
        {legSides(position).map(({ symbol, side }) => (
          <li key={symbol} className="flex items-baseline gap-2 text-[13px]">
            <span className="flex w-11 shrink-0 items-center gap-1">
              <span
                className="inline-block h-[6px] w-[6px] shrink-0"
                style={{
                  background: side === "SELL" ? "var(--brass)" : "var(--steel)",
                  borderRadius: "1px",
                }}
                aria-hidden
              />
              <span className="mono uppercase text-[color:var(--text-dim)]">{side}</span>
            </span>
            <span className="contract flex-1 truncate text-[color:var(--text)]">
              {contractLabel(symbol)}
            </span>
            <span className="mono shrink-0 text-[12px] text-[color:var(--text-faint)]">
              {legLabel(position, side)}
            </span>
          </li>
        ))}
      </ul>

      {/* metrics — four columns, mono, tabular. The mark is a VALUE, never a
          change: unsigned, uncoloured, and named for what it is per structure.
          UNREALISED above is the only P&L figure on the card. */}
      <div className="mt-3 grid grid-cols-4 gap-2 border-t border-[color:var(--line)] pt-3">
        {(
          [
            ["entry", dollars(position.entry_credit, 2), undefined],
            [
              position.entry_credit > 0 ? "cost to close" : "value now",
              `$${Math.abs(position.current_value).toLocaleString("en-US", { maximumFractionDigits: 0 })}`,
              "The structure's current market value — not profit or loss.",
            ],
            ["max loss", dollars(position.max_loss, 2), undefined],
            ["held", daysHeld(position), undefined],
          ] as const
        ).map(([label, value, hint]) => (
          <div key={label} title={hint}>
            <p className="mono text-[11px] uppercase tracking-wider text-[color:var(--text-dim)]">
              {label}
            </p>
            <p className="mono mt-0.5 text-[14px] tabular-nums text-[color:var(--text)]">{value}</p>
          </div>
        ))}
      </div>

      {/* exit rules as chips; the nearest one takes the accent */}
      <div className="mt-3 flex flex-wrap gap-1.5 border-t border-[color:var(--line)] pt-3">
        {exitChips(position, status).map((chip) => (
          <ExitChip key={chip.label} {...chip} />
        ))}
      </div>
    </article>
  );
}

export function PositionsClient() {
  const { data: status } = useStatus();
  const { data: positions, isLoading } = usePositions();
  const { data: closed } = useClosedPositions();
  const { data: risk } = useRisk();

  const rows = positions ?? [];
  const closedRows = closed ?? [];
  const totalPnl = rows.reduce((acc, p) => acc + p.unrealized_pnl, 0);
  const totalRisk = rows.reduce((acc, p) => acc + p.max_loss, 0);
  const realizedTotal = closedRows.reduce((acc, p) => acc + (p.realized_pnl ?? 0), 0);
  const fmt = (v: number) => `$${v.toLocaleString("en-US", { minimumFractionDigits: 2 })}`;

  return (
    <div className="flex min-h-screen flex-col">
      <Header status={status} tab="positions" />

      <main className="flex-1 p-4">
        <h1 className="font-display text-[length:var(--fs-md)]">Positions</h1>
        {/* Present, but not the headline. Performance over a few days is noise. */}
        <p className="mt-2 max-w-2xl text-[14px] leading-relaxed text-[color:var(--text-dim)]">
          A few days of paper results are not evidence of edge. This is the
          record of what the desk actually did.
        </p>

        {/* header strip — four labelled figures. Equity is a denominator for
            the risk limits, not a scoreboard: same scale, never coloured. */}
        <div className="panel mt-4 grid grid-cols-2 gap-4 p-4 sm:grid-cols-4">
          <Figure label="open" value={`${rows.length} · ${dollars(totalRisk)} at risk`} />
          <Figure
            label="unrealised"
            value={money(totalPnl)}
            tone={totalPnl >= 0 ? "var(--verdigris)" : "var(--brass)"}
          />
          <Figure
            label="realised"
            value={money(realizedTotal)}
            tone={realizedTotal >= 0 ? "var(--verdigris)" : "var(--brass)"}
          />
          <Figure
            label="equity vs starting"
            value={
              status?.equity != null && status?.starting_equity != null
                ? `${fmt(status.equity)} / ${fmt(status.starting_equity)}`
                : "—"
            }
          />
        </div>

        {/* tier progress — the mechanism lives where the closes that earn it live */}
        {risk && (
          <div className="panel mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5">
            <span className="flex items-center gap-2">
              <span className="font-display text-[15px]">Tier {risk.tier}</span>
              <TierPips tier={risk.tier} />
            </span>
            <span className="mono text-[13px] text-[color:var(--text-dim)]">
              {(risk.max_loss_pct * 100).toFixed(1)}% per trade ·{" "}
              {(risk.portfolio_pct * 100).toFixed(1)}% deployed
            </span>
            <span className="mono ml-auto text-[13px] text-[color:var(--text-dim)]">
              {risk.next_promotion}
            </span>
          </div>
        )}

        {/* open positions as cards */}
        {rows.length === 0 ? (
          <p className="mt-6 text-sm text-[color:var(--text-dim)]">
            {isLoading
              ? "Loading positions."
              : "No open positions. The desk opens one when a candidate clears every gate and the budget has room."}
          </p>
        ) : (
          <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
            {rows.map((position) => (
              <PositionCard key={position.id} position={position} status={status} />
            ))}
          </div>
        )}

        {/* closed trades — a record people scan stays a table */}
        <section className="mt-8" aria-label="Closed trades">
          <div className="flex flex-wrap items-baseline justify-between gap-4">
            <h2 className="font-display text-[length:var(--fs-sm)]">Closed trades</h2>
            {closedRows.length > 0 && (
              <p className="mono text-[13px] text-[color:var(--text-dim)]">
                {closedRows.length} closed · realised{" "}
                <span
                  style={{
                    color: realizedTotal >= 0 ? "var(--verdigris)" : "var(--brass)",
                  }}
                >
                  {money(realizedTotal)}
                </span>
              </p>
            )}
          </div>
          {closedRows.length === 0 ? (
            <p className="mt-3 text-sm text-[color:var(--text-dim)]">
              No closed trades yet. A close fires on the profit target, the loss
              limit, the days-to-expiry threshold, or the assignment defence —
              and lands here with its realised P&L and the rule that closed it.
            </p>
          ) : (
            <>
              <div className="panel mt-3 overflow-x-auto">
                <table className="w-full min-w-[46rem] border-collapse text-left">
                  <thead>
                    <tr className="border-b border-[color:var(--line)]">
                      {["symbol", "structure", "opened", "closed", "held", "entry", "realised", "closed by"].map(
                        (h) => (
                          <th
                            key={h}
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
                    {closedRows.map((trade) => (
                      <tr
                        key={trade.id}
                        className="border-b border-[color:var(--line)] last:border-0"
                      >
                        <td className="px-3 py-2">
                          <span className="flex items-center gap-2">
                            <SymbolMark symbol={trade.symbol} size={24} />
                            <span className="mono text-[14px]">{trade.symbol}</span>
                          </span>
                        </td>
                        <td className="px-3 py-2 text-[14px]">
                          {trade.kind ? structureLabel(trade.kind) : "—"}
                        </td>
                        <td className="mono px-3 py-2 text-[13px] text-[color:var(--text-dim)]">
                          {trade.opened_at ? timeAgo(trade.opened_at) : "—"}
                        </td>
                        <td className="mono px-3 py-2 text-[13px] text-[color:var(--text-dim)]">
                          {trade.closed_at ? timeAgo(trade.closed_at) : "—"}
                        </td>
                        <td className="mono px-3 py-2 text-[14px]">
                          {trade.days_held !== null ? `${trade.days_held}d` : "—"}
                        </td>
                        <td className="mono px-3 py-2 text-[14px] tabular-nums">
                          {dollars(trade.entry_credit, 2)}
                        </td>
                        <td
                          className="mono px-3 py-2 text-[14px] tabular-nums"
                          style={{
                            color:
                              (trade.realized_pnl ?? 0) >= 0
                                ? "var(--verdigris)"
                                : "var(--brass)",
                          }}
                        >
                          {trade.realized_pnl !== null ? (
                            money(trade.realized_pnl)
                          ) : (
                            <span
                              className="text-[12px] text-[color:var(--text-dim)]"
                              title="The close filled at the broker but its fill price could not be recovered — stated rather than estimated."
                            >
                              closed at broker · realised unavailable
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <span
                            className="mono whitespace-nowrap rounded-full border border-[color:var(--line)] px-2.5 py-1 text-[12px] font-semibold text-[color:var(--text-dim)]"
                          >
                            {EXIT_LABEL[trade.exit_reason ?? ""] ?? trade.exit_reason ?? "—"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* provenance: realised figures recovered by reconciliation come
                  from the broker's own close fills, and the corrections say so */}
              <p className="mono mt-2 text-[12px] text-[color:var(--text-faint)]">
                Where a close filled after the submission poll, its realised
                figure was recovered from the broker&rsquo;s own fills —{" "}
                <Link
                  href="/audit?action=CORRECTION&grouped=0&q=recovered"
                  className="t-fast underline decoration-[color:var(--line)] underline-offset-2 hover:text-[color:var(--text)]"
                >
                  the corrections are in the audit log
                </Link>
                .
              </p>
            </>
          )}
        </section>

        <p className="mono mt-6 max-w-2xl text-[12px] leading-relaxed text-[color:var(--text-dim)]">
          Every position is defined-risk: the maximum loss was computed and
          gated before submission, and each spread was filled as a single atomic
          multi-leg order. Exits fire on the profit target, the loss limit, the
          days-to-expiry threshold, or the assignment defence.
        </p>
      </main>
    </div>
  );
}
