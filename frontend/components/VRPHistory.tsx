"use client";

/**
 * The variance risk premium over time — IV and RV as two lines with the gap
 * between them filled: --brass where implied leads (the market overpaying for
 * movement), --steel where realized leads.
 *
 * The IV side comes from the snapshot poller and exists only since first run,
 * because Alpaca serves no historical IV. The window is labelled with exactly
 * how much history it holds — "since first run, 2 days" — and never implies
 * more. An honest short chart beats a fabricated long one.
 */

import { useMemo } from "react";

import { useVrpHistory } from "@/lib/api";
import type { VrpHistory } from "@/lib/types";

/** The window, from the ACTUAL first/last observation timestamps — in hours
 *  while it is under a day, so "0d window · 52 obs" can never appear. */
function spanLabel(data: VrpHistory): string {
  if (data.first_ts && data.last_ts) {
    const ms = new Date(data.last_ts).getTime() - new Date(data.first_ts).getTime();
    const hours = ms / 3_600_000;
    if (hours < 1) return "<1h";
    if (hours < 24) return `${hours.toFixed(hours < 10 ? 1 : 0)}h`;
    return `${Math.round(hours / 24)}d`;
  }
  return `${data.window_days}d`;
}

const W = 340;
const H = 100;
const PAD_L = 30;
const PAD_R = 10;
const PAD_T = 8;
const PAD_B = 16;

export function VRPHistory({ symbol }: { symbol: string }) {
  const { data } = useVrpHistory(symbol);

  const geo = useMemo(() => {
    const rows = (data?.series ?? []).filter((r) => r.iv > 0 && r.rv !== null);
    if (rows.length < 2) return null;

    const values = rows.flatMap((r) => [r.iv, r.rv as number]);
    const minV = Math.min(...values) * 0.92;
    const maxV = Math.max(...values) * 1.06;

    const x = (i: number) => PAD_L + (i / (rows.length - 1)) * (W - PAD_L - PAD_R);
    const y = (v: number) => H - PAD_B - ((v - minV) / (maxV - minV || 1)) * (H - PAD_T - PAD_B);

    // Fill each segment by whichever line leads across it.
    const segments = rows.slice(0, -1).map((r, i) => {
      const next = rows[i + 1]!;
      const lead = (r.iv + next.iv) / 2 >= ((r.rv as number) + (next.rv as number)) / 2;
      return {
        points: [
          `${x(i)},${y(r.iv)}`,
          `${x(i + 1)},${y(next.iv)}`,
          `${x(i + 1)},${y(next.rv as number)}`,
          `${x(i)},${y(r.rv as number)}`,
        ].join(" "),
        fill: lead ? "var(--brass)" : "var(--steel)",
      };
    });

    return {
      rows,
      segments,
      iv: rows.map((r, i) => `${x(i)},${y(r.iv)}`).join(" "),
      rv: rows.map((r, i) => `${x(i)},${y(r.rv as number)}`).join(" "),
      minV,
      maxV,
      firstDate: rows[0]!.date,
      lastDate: rows.at(-1)!.date,
    };
  }, [data]);

  if (!data || !geo) {
    return (
      <p className="mono text-[10px] leading-relaxed text-[color:var(--text-dim)]">
        {data
          ? `${data.observations} observation(s) so far — the poller builds this history forward from first run; the chart fills in as days accrue.`
          : "loading vrp history…"}
      </p>
    );
  }

  return (
    <div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full max-w-[340px]"
        role="img"
        aria-label={`Implied versus realized volatility over ${data.window_days} day(s) of self-collected history`}
      >
        <line x1={PAD_L} y1={H - PAD_B} x2={W - PAD_R} y2={H - PAD_B} stroke="var(--line)" />
        <text x={PAD_L - 4} y={PAD_T + 8} textAnchor="end" className="mono" fontSize={8} fill="var(--text-dim)">
          {(geo.maxV * 100).toFixed(0)}
        </text>
        <text x={PAD_L - 4} y={H - PAD_B} textAnchor="end" className="mono" fontSize={8} fill="var(--text-dim)">
          {(geo.minV * 100).toFixed(0)}
        </text>

        {geo.segments.map((s, i) => (
          <polygon key={i} points={s.points} fill={s.fill} opacity={0.16} />
        ))}
        <polyline points={geo.iv} fill="none" stroke="var(--brass)" strokeWidth={1.5} />
        <polyline points={geo.rv} fill="none" stroke="var(--steel)" strokeWidth={1.5} />

        <text x={PAD_L} y={H - 5} className="mono" fontSize={8} fill="var(--text-dim)">
          {geo.firstDate.slice(5)}
        </text>
        <text x={W - PAD_R} y={H - 5} textAnchor="end" className="mono" fontSize={8} fill="var(--text-dim)">
          {geo.lastDate.slice(5)}
        </text>
      </svg>
      {/* The honest label. Never implies more history than exists. */}
      <p className="mono mt-1 text-[9px] text-[color:var(--text-dim)]">
        since first run · {spanLabel(data)} window · {data.observations} obs · brass = iv leads,
        steel = rv leads
      </p>
    </div>
  );
}
