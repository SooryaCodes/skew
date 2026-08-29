"use client";

/**
 * The volatility cone — where movement at each horizon sits inside this
 * underlying's own 252-day distribution.
 *
 * Percentile bands (10/25/50/75/90) of realized vol across 10–90 day horizons,
 * in --steel-dim at graduated opacity, with the current trailing realized vol
 * dotted across in ink and today's implied vol as a single --brass dot at the
 * front expiry's horizon.
 *
 * This is what a vol trader actually looks at. "RV percentile 25" becomes an
 * argument, and NVDA's abstention becomes visible: current RV pinned at the
 * top of its own cone, IV sitting below it — elevated vol that is being
 * realized, not collected.
 */

import { useMemo } from "react";

import type { ConePoint } from "@/lib/types";

const W = 340;
const H = 120;
const PAD_L = 30;
const PAD_R = 26;
const PAD_T = 8;
const PAD_B = 16;

interface Props {
  cone: ConePoint[];
  ivAtm: number;
  /** DTE of the front expiry — where the IV dot sits on the horizon axis. */
  ivDte: number;
}

export function VolCone({ cone, ivAtm, ivDte }: Props) {
  const geo = useMemo(() => {
    if (cone.length < 2) return null;
    const sorted = [...cone].sort((a, b) => a.horizon - b.horizon);
    const minH = sorted[0]!.horizon;
    const maxH = sorted.at(-1)!.horizon;
    const values = sorted.flatMap((c) => [c.p10, c.p90, c.current]).concat(ivAtm);
    const minV = Math.min(...values) * 0.92;
    const maxV = Math.max(...values) * 1.05;

    const x = (h: number) => PAD_L + ((h - minH) / (maxH - minH || 1)) * (W - PAD_L - PAD_R);
    const y = (v: number) => H - PAD_B - ((v - minV) / (maxV - minV || 1)) * (H - PAD_T - PAD_B);

    const band = (hi: (c: ConePoint) => number, lo: (c: ConePoint) => number) =>
      [
        ...sorted.map((c) => `${x(c.horizon)},${y(hi(c))}`),
        ...[...sorted].reverse().map((c) => `${x(c.horizon)},${y(lo(c))}`),
      ].join(" ");

    return {
      sorted,
      outer: band((c) => c.p90, (c) => c.p10),
      inner: band((c) => c.p75, (c) => c.p25),
      median: sorted.map((c) => `${x(c.horizon)},${y(c.p50)}`).join(" "),
      current: sorted.map((c) => ({ cx: x(c.horizon), cy: y(c.current) })),
      iv: { cx: x(Math.min(Math.max(ivDte, minH), maxH)), cy: y(ivAtm) },
      x,
      minV,
      maxV,
    };
  }, [cone, ivAtm, ivDte]);

  if (!geo) {
    return (
      <p className="mono text-[10px] text-[color:var(--text-dim)]">
        cone unavailable — not enough bar history for percentile bands
      </p>
    );
  }

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="h-auto w-full max-w-[340px]"
      role="img"
      aria-label="Realized volatility percentile cone with current implied vol"
    >
      <line x1={PAD_L} y1={H - PAD_B} x2={W - PAD_R} y2={H - PAD_B} stroke="var(--line)" />
      <text x={PAD_L - 4} y={PAD_T + 8} textAnchor="end" className="mono" fontSize={8} fill="var(--text-dim)">
        {(geo.maxV * 100).toFixed(0)}
      </text>
      <text x={PAD_L - 4} y={H - PAD_B} textAnchor="end" className="mono" fontSize={8} fill="var(--text-dim)">
        {(geo.minV * 100).toFixed(0)}
      </text>

      {/* bands: 10–90 faint, 25–75 stronger, median as a line */}
      <polygon points={geo.outer} fill="var(--steel-dim)" opacity={0.28} />
      <polygon points={geo.inner} fill="var(--steel-dim)" opacity={0.5} />
      <polyline points={geo.median} fill="none" stroke="var(--steel)" strokeWidth={1} />

      {/* current trailing RV per horizon — ink dots, dotted connector */}
      <polyline
        points={geo.current.map((p) => `${p.cx},${p.cy}`).join(" ")}
        fill="none"
        stroke="var(--text-dim)"
        strokeWidth={1}
        strokeDasharray="1 3"
      />
      {geo.current.map((p, i) => (
        <circle key={i} cx={p.cx} cy={p.cy} r={1.8} fill="var(--text)" />
      ))}

      {/* today's implied vol — the brass dot the whole chart exists to place */}
      <circle cx={geo.iv.cx} cy={geo.iv.cy} r={3.5} fill="var(--brass)" />
      <text
        x={geo.iv.cx + 6}
        y={geo.iv.cy + 3}
        className="mono"
        fontSize={8}
        fill="var(--text-dim)"
      >
        iv
      </text>

      {geo.sorted.map((c) => (
        <text
          key={c.horizon}
          x={geo.x(c.horizon)}
          y={H - 5}
          textAnchor="middle"
          className="mono"
          fontSize={8}
          fill="var(--text-dim)"
        >
          {c.horizon}
        </text>
      ))}
    </svg>
  );
}
