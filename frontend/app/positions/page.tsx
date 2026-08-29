"use client";

/**
 * Positions and P&L — deliberately the second screen.
 *
 * The product's claim is that risk governance matters more than returns, so the
 * landing view is the decision surface and this is behind a tab. That is a
 * design argument, not an oversight: leading with a P&L number over a few days
 * of paper trading would be leading with noise.
 */

import { Header } from "@/components/Header";
import { contractLabel, dollars, money, structureLabel } from "@/lib/format";
import { usePositions, useRisk, useStatus, useUniverse } from "@/lib/api";

export default function PositionsPage() {
  const { data: status } = useStatus();
  const { data: universe } = useUniverse();
  const { data: positions, isLoading } = usePositions();
  const { data: risk } = useRisk();

  const rows = positions ?? [];
  const totalPnl = rows.reduce((acc, p) => acc + p.unrealized_pnl, 0);
  const totalRisk = rows.reduce((acc, p) => acc + p.max_loss, 0);
  const focused = (universe ?? [])[0];

  return (
    <div className="flex min-h-screen flex-col">
      <Header focused={focused} status={status} tab="positions" />

      <main className="flex-1 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-4">
          <h1 className="font-display text-[length:var(--fs-md)]">Positions</h1>
          <p className="mono text-[11px] text-[color:var(--muted)]">
            {rows.length} open · {dollars(totalRisk)} at risk
            {risk && ` · tier ${risk.tier}`}
          </p>
        </div>

        {/* Present, but not the headline. Performance over a few days is noise. */}
        <p className="mono mt-1 text-[11px] text-[color:var(--muted)]">
          unrealised {money(totalPnl)} — over a handful of paper-trading days this
          number is noise, and the desk does not lead with it
        </p>

        {rows.length === 0 ? (
          <p className="mt-6 text-sm text-[color:var(--muted)]">
            {isLoading
              ? "Loading positions."
              : "No open positions. The desk holds nothing until a candidate clears every gate and the bounded selector picks it."}
          </p>
        ) : (
          <div className="panel mt-4 overflow-x-auto">
            <table className="w-full min-w-[52rem] border-collapse text-left">
              <thead>
                <tr className="border-b border-[color:var(--line)]">
                  {["symbol", "structure", "legs", "dte", "entry", "value", "unrealised", "max loss"].map(
                    (h) => (
                      <th
                        key={h}
                        scope="col"
                        className="mono px-3 py-2 text-[10px] font-medium uppercase tracking-wider text-[color:var(--muted)]"
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {rows.map((position) => (
                  <tr key={position.id} className="border-b border-[color:var(--line)] last:border-0">
                    <td className="mono px-3 py-2 text-[12px]">{position.symbol}</td>
                    <td className="px-3 py-2 text-[12px]">
                      {position.kind ? structureLabel(position.kind) : "—"}
                    </td>
                    <td className="px-3 py-2">
                      <ul>
                        {position.legs.map((leg) => (
                          <li
                            key={leg}
                            className="contract text-[10px] text-[color:var(--muted)]"
                          >
                            {contractLabel(leg)}
                          </li>
                        ))}
                      </ul>
                    </td>
                    <td className="mono px-3 py-2 text-[12px]">{position.dte}</td>
                    <td className="mono px-3 py-2 text-[12px]">
                      {dollars(position.entry_credit, 2)}
                    </td>
                    <td className="mono px-3 py-2 text-[12px] text-[color:var(--muted)]">
                      {money(position.current_value, 0)}
                    </td>
                    <td
                      className="mono px-3 py-2 text-[12px]"
                      style={{
                        // Deliberately NOT --breach. That colour is spent on
                        // failed gates and nothing else, losses included.
                        color:
                          position.unrealized_pnl >= 0 ? "var(--cheap)" : "var(--rich)",
                      }}
                    >
                      {money(position.unrealized_pnl)}
                    </td>
                    <td className="mono px-3 py-2 text-[12px]">
                      {dollars(position.max_loss, 2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="mono mt-6 max-w-2xl text-[10px] leading-relaxed text-[color:var(--muted)]">
          Every position is defined-risk: the maximum loss was computed and
          gated before submission, and each spread was filled as a single atomic
          multi-leg order. Exits fire on a 50% profit target, a loss limit, or
          the days-to-expiry threshold.
        </p>
      </main>
    </div>
  );
}
