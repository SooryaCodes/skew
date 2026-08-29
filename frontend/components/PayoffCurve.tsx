"use client";

/**
 * Payoff at expiry across underlying price.
 *
 * Computed from intrinsic values on the client — the same arithmetic the
 * backend's `expiry_pnl` does, and it agrees with it because both are just
 * `Σ signed_ratio × intrinsic × 100` minus the entry price. Doing it here
 * rather than shipping a curve keeps the API small and lets the chart resample
 * smoothly at any width.
 *
 * Recharts, per docs/02-TECH-STACK.md. Sufficient and fast to write.
 */

import { useMemo } from "react";
import {
  Area,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { money, num } from "@/lib/format";
import type { Structure } from "@/lib/types";

const MULTIPLIER = 100;

function intrinsic(spot: number, strike: number, right: "CALL" | "PUT"): number {
  return right === "CALL" ? Math.max(0, spot - strike) : Math.max(0, strike - spot);
}

function payoffAt(structure: Structure, spot: number): number {
  let value = 0;
  let entry = 0;
  for (const leg of structure.legs) {
    const sign = leg.side === "BUY" ? leg.ratio_qty : -leg.ratio_qty;
    value += sign * intrinsic(spot, leg.strike, leg.right) * MULTIPLIER * structure.qty;
    entry += sign * leg.mid * MULTIPLIER * structure.qty;
  }
  return value - entry;
}

export function PayoffCurve({ structure }: { structure: Structure }) {
  const data = useMemo(() => {
    const strikes = structure.legs.map((l) => l.strike);
    const lo = Math.min(...strikes, structure.spot);
    const hi = Math.max(...strikes, structure.spot);
    const pad = Math.max((hi - lo) * 1.6, structure.spot * 0.035);

    const from = Math.max(0.01, lo - pad);
    const to = hi + pad;
    const steps = 90;

    return Array.from({ length: steps + 1 }, (_, i) => {
      const price = from + ((to - from) * i) / steps;
      return { price, pnl: payoffAt(structure, price) };
    });
  }, [structure]);

  const domain = useMemo(() => {
    const values = data.map((d) => d.pnl);
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    const pad = Math.max((hi - lo) * 0.15, 10);
    return [lo - pad, hi + pad] as [number, number];
  }, [data]);

  return (
    <div className="h-28 w-full" aria-label="Payoff at expiry">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
          <defs>
            <linearGradient id="payoff-up" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--cheap)" stopOpacity="0.22" />
              <stop offset="100%" stopColor="var(--cheap)" stopOpacity="0" />
            </linearGradient>
          </defs>

          <XAxis
            dataKey="price"
            type="number"
            domain={["dataMin", "dataMax"]}
            tick={{ fill: "var(--muted)", fontSize: 9 }}
            tickFormatter={(v: number) => num(v, 0)}
            axisLine={{ stroke: "var(--line)" }}
            tickLine={false}
            interval="preserveStartEnd"
            height={14}
          />
          <YAxis hide domain={domain} />

          <ReferenceLine y={0} stroke="var(--line)" strokeWidth={1} />
          <ReferenceLine
            x={structure.spot}
            stroke="var(--muted)"
            strokeWidth={1}
            strokeDasharray="2 3"
          />
          {structure.breakevens.map((b) => (
            <ReferenceLine key={b} x={b} stroke="var(--line)" strokeDasharray="1 3" />
          ))}

          <Area
            type="monotone"
            dataKey="pnl"
            stroke="none"
            fill="url(#payoff-up)"
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="pnl"
            stroke="var(--text)"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />

          <Tooltip
            cursor={{ stroke: "var(--line)" }}
            contentStyle={{
              background: "var(--surface-raised)",
              border: "1px solid var(--line)",
              borderRadius: "var(--radius)",
              fontSize: 11,
            }}
            labelFormatter={(label) => `underlying ${num(Number(label), 2)}`}
            formatter={(value) => [money(Number(value), 0), "P&L at expiry"]}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
