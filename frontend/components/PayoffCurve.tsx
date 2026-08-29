"use client";

/**
 * Payoff at expiry across underlying price.
 *
 * Profit region shaded --verdigris, loss region --oxide (both at 12% — the
 * oxide-only-for-failed-gates rule is relaxed here by explicit design
 * direction, and only as a 12% field, never as text). Current spot is a
 * labelled marker — without it the chart is abstract — with the ±1σ move over
 * the structure's life shaded across the x axis so "how far is the breakeven"
 * has a ruler next to it. Max profit and max loss sit as asymptote labels at
 * the right edge.
 */

import { useMemo } from "react";
import {
  Area,
  ComposedChart,
  Line,
  ReferenceArea,
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

interface Props {
  structure: Structure;
  /** Annualised 20d realized vol of the underlying — sizes the ±1σ band. */
  rv20?: number;
}

export function PayoffCurve({ structure, rv20 }: Props) {
  const sigma = rv20 ? structure.spot * rv20 * Math.sqrt(Math.max(structure.dte, 1) / 365) : 0;

  const data = useMemo(() => {
    const strikes = structure.legs.map((l) => l.strike);
    const lo = Math.min(...strikes, structure.spot - sigma);
    const hi = Math.max(...strikes, structure.spot + sigma);
    const pad = Math.max((hi - lo) * 0.35, structure.spot * 0.01);
    const from = Math.max(0.01, lo - pad);
    const to = hi + pad;
    const steps = 120;

    return Array.from({ length: steps + 1 }, (_, i) => {
      const price = from + ((to - from) * i) / steps;
      const pnl = payoffAt(structure, price);
      return { price, pnl, pos: Math.max(0, pnl), neg: Math.min(0, pnl) };
    });
  }, [structure, sigma]);

  const domain = useMemo(() => {
    const values = data.map((d) => d.pnl);
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    const pad = Math.max((hi - lo) * 0.15, 10);
    return [lo - pad, hi + pad] as [number, number];
  }, [data]);

  return (
    <div className="relative h-32 w-full" aria-label="Payoff at expiry">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 4, right: 46, bottom: 0, left: 4 }}>
          <XAxis
            dataKey="price"
            type="number"
            domain={["dataMin", "dataMax"]}
            tick={{ fill: "var(--text-dim)", fontSize: 9 }}
            tickFormatter={(v: number) => num(v, 0)}
            axisLine={{ stroke: "var(--line)" }}
            tickLine={false}
            interval="preserveStartEnd"
            height={14}
          />
          <YAxis hide domain={domain} />

          {/* ±1σ over the structure's life — the ruler behind the picture */}
          {sigma > 0 && (
            <ReferenceArea
              x1={structure.spot - sigma}
              x2={structure.spot + sigma}
              fill="var(--steel-dim)"
              fillOpacity={0.14}
              strokeOpacity={0}
            />
          )}

          <ReferenceLine y={0} stroke="var(--line)" strokeWidth={1} />

          {/* current spot — labelled, or the chart is abstract */}
          <ReferenceLine
            x={structure.spot}
            stroke="var(--text-dim)"
            strokeWidth={1}
            strokeDasharray="2 3"
            label={{
              value: `spot ${num(structure.spot, 0)}`,
              position: "insideTopLeft",
              fill: "var(--text-dim)",
              fontSize: 9,
              fontFamily: "var(--font-mono)",
            }}
          />

          {/* breakevens as hairlines carrying their values */}
          {structure.breakevens.map((b) => (
            <ReferenceLine
              key={b}
              x={b}
              stroke="var(--line)"
              strokeDasharray="1 3"
              label={{
                value: num(b, 2),
                position: "insideBottomLeft",
                fill: "var(--text-dim)",
                fontSize: 9,
                fontFamily: "var(--font-mono)",
              }}
            />
          ))}

          {/* profit verdigris, loss oxide — 12% fields */}
          <Area
            type="monotone"
            dataKey="pos"
            stroke="none"
            fill="var(--verdigris)"
            fillOpacity={0.12}
            isAnimationActive={false}
          />
          <Area
            type="monotone"
            dataKey="neg"
            stroke="none"
            fill="var(--oxide)"
            fillOpacity={0.12}
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
              background: "var(--panel-alt)",
              border: "1px solid var(--line)",
              borderRadius: "var(--radius)",
              fontSize: 11,
            }}
            labelFormatter={(label) => `underlying ${num(Number(label), 2)}`}
            formatter={(value) => [money(Number(value), 0), "P&L at expiry"]}
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* asymptote labels at the right edge */}
      <span className="mono pointer-events-none absolute right-0 top-1 text-[9px] text-[color:var(--text-dim)]">
        max {money(structure.max_profit, 0)}
      </span>
      <span className="mono pointer-events-none absolute bottom-4 right-0 text-[9px] text-[color:var(--text-dim)]">
        {money(-structure.max_loss, 0)}
      </span>
    </div>
  );
}
