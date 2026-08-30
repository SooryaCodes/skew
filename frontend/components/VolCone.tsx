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
import { nearestIndex, useCrosshair } from "@/lib/useCrosshair";

const W = 340;
const H = 190;
const PAD_L = 30;
const PAD_R = 44; // room for the band labels at the right edge
const PAD_T = 10;
const PAD_B = 18;

interface Props {
  cone: ConePoint[];
  ivAtm: number;
  /** DTE of the front expiry — where the IV dot sits on the horizon axis. */
  ivDte: number;
}

/** Where current RV sits inside its own percentile band, from the band edges
 *  the backend actually computed — piecewise between known percentiles, capped
 *  at the edges. Display maths only; nothing here feeds a decision. */
function bandPercentile(c: ConePoint): number {
  const marks: Array<[number, number]> = [
    [10, c.p10],
    [25, c.p25],
    [50, c.p50],
    [75, c.p75],
    [90, c.p90],
  ];
  if (c.current <= c.p10) return 10;
  if (c.current >= c.p90) return 90;
  for (let i = 0; i < marks.length - 1; i += 1) {
    const [pctLo, lo] = marks[i]!;
    const [pctHi, hi] = marks[i + 1]!;
    if (c.current >= lo && c.current <= hi) {
      const t = hi === lo ? 0 : (c.current - lo) / (hi - lo);
      return Math.round(pctLo + t * (pctHi - pctLo));
    }
  }
  return 50;
}

export function VolCone({ cone, ivAtm, ivDte }: Props) {
  const { svgRef, pointerX, handlers } = useCrosshair(W);
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

    const last = sorted.at(-1)!;
    return {
      sorted,
      xs: sorted.map((c) => x(c.horizon)),
      outer: band((c) => c.p90, (c) => c.p10),
      inner: band((c) => c.p75, (c) => c.p25),
      median: sorted.map((c) => `${x(c.horizon)},${y(c.p50)}`).join(" "),
      current: sorted.map((c) => ({ cx: x(c.horizon), cy: y(c.current) })),
      iv: { cx: x(Math.min(Math.max(ivDte, minH), maxH)), cy: y(ivAtm) },
      // Direct labels at the right edge — opacity alone did not name the bands.
      bandLabels: [
        { text: "90th", cy: y(last.p90) },
        { text: "75th", cy: y(last.p75) },
        { text: "median", cy: y(last.p50) },
        { text: "25th", cy: y(last.p25) },
        { text: "10th", cy: y(last.p10) },
      ],
      rvLabel: { cy: y(last.current) },
      x,
      minV,
      maxV,
    };
  }, [cone, ivAtm, ivDte]);

  if (!geo) {
    return (
      <p className="mono text-[12px] text-[color:var(--text-dim)]">
        cone unavailable — not enough bar history for percentile bands
      </p>
    );
  }

  // Crosshair: nearest real horizon. Resting readout = the horizon nearest the
  // front expiry, where the IV dot lives.
  const defaultIndex = nearestIndex(
    geo.sorted.map((c) => Math.abs(c.horizon - ivDte)),
    0,
  );
  const hoverIndex = pointerX === null ? defaultIndex : nearestIndex(geo.xs, pointerX);
  const hovered = geo.sorted[hoverIndex]!;
  const hoveredX = geo.xs[hoverIndex]!;
  const isDefault = pointerX === null;

  return (
    <svg
      ref={svgRef}
      {...handlers}
      viewBox={`0 0 ${W} ${H}`}
      className="h-auto w-full touch-none max-w-[380px]"
      role="img"
      aria-label="Realized volatility percentile cone with current implied vol"
    >
      <line x1={PAD_L} y1={H - PAD_B} x2={W - PAD_R} y2={H - PAD_B} stroke="var(--line)" />
      <text x={PAD_L - 4} y={PAD_T + 8} textAnchor="end" className="mono" fontSize={9.5} fill="var(--text-dim)">
        {(geo.maxV * 100).toFixed(0)}
      </text>
      <text x={PAD_L - 4} y={H - PAD_B} textAnchor="end" className="mono" fontSize={9.5} fill="var(--text-dim)">
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

      {/* crosshair — snapped to a real horizon */}
      {!isDefault && (
        <line
          x1={hoveredX}
          y1={PAD_T}
          x2={hoveredX}
          y2={H - PAD_B}
          stroke="var(--text-faint)"
          strokeWidth={0.75}
        />
      )}
      <circle
        cx={hoveredX}
        cy={geo.current[hoverIndex]!.cy}
        r={3}
        fill="var(--text)"
      />
      <text
        x={W - PAD_R}
        y={PAD_T + 2}
        textAnchor="end"
        className="mono"
        fontSize={9}
        fill="var(--text-dim)"
      >
        {hovered.horizon}d · median {(hovered.p50 * 100).toFixed(1)} · current{" "}
        {(hovered.current * 100).toFixed(1)} · {bandPercentile(hovered)}th pct
      </text>

      {/* today's implied vol — the brass dot the whole chart exists to place */}
      <circle cx={geo.iv.cx} cy={geo.iv.cy} r={3.5} fill="var(--brass)" />
      <text
        x={geo.iv.cx + 6}
        y={geo.iv.cy + 3}
        className="mono"
        fontSize={9.5}
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
          fontSize={9.5}
          fill="var(--text-dim)"
        >
          {c.horizon}
        </text>
      ))}

      {/* the bands, named — collision-free enough at this height */}
      {geo.bandLabels.map((label) => (
        <text
          key={label.text}
          x={W - PAD_R + 5}
          y={label.cy + 2.5}
          className="mono"
          fontSize={9}
          fill="var(--text-dim)"
        >
          {label.text}
        </text>
      ))}
    </svg>
  );
}
