"use client";

/**
 * The skew curve — the identity of the application.
 *
 * Implied volatility plotted across strike prices forms a curve: lower strikes
 * carry higher IV because people pay up for downside protection. That asymmetry
 * is called the skew, and it is literally what the product is named after.
 *
 * It is deliberately not a chart in a panel. It is the header's spine — thin
 * stroke, ambient, redrawing as data updates. A visitor sees the thesis before
 * reading a word.
 *
 * Hand-rolled SVG rather than Recharts: this needs to be a single continuous
 * stroke behind other content with no axes, no grid, no tooltip and no
 * container. A chart library would be more friction than help.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import type { SkewPoint } from "@/lib/types";

const WIDTH = 1000;
const HEIGHT = 84;
const PAD_X = 8;
const PAD_Y = 10;

interface Props {
  points: SkewPoint[];
  spot: number;
  accent?: string;
  /** Redraws when this changes — the symbol under focus, or the cycle timestamp. */
  redrawKey?: string;
}

function catmullRomPath(coords: Array<[number, number]>): string {
  if (coords.length === 0) return "";
  if (coords.length < 3) {
    return coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x} ${y}`).join(" ");
  }

  // A smooth curve through every point. The skew is a smooth surface in
  // reality; drawing it as straight segments would imply structure in the
  // strike spacing that is not there.
  let d = `M${coords[0]![0]} ${coords[0]![1]}`;
  for (let i = 0; i < coords.length - 1; i += 1) {
    const p0 = coords[Math.max(0, i - 1)]!;
    const p1 = coords[i]!;
    const p2 = coords[i + 1]!;
    const p3 = coords[Math.min(coords.length - 1, i + 2)]!;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C${c1x} ${c1y} ${c1y === c2y ? c2x : c2x} ${c2y} ${p2[0]} ${p2[1]}`;
  }
  return d;
}

export function SkewCurve({ points, spot, accent = "var(--brass)", redrawKey }: Props) {
  const pathRef = useRef<SVGPathElement | null>(null);
  const [length, setLength] = useState(1200);

  const geometry = useMemo(() => {
    const usable = points.filter((p) => Number.isFinite(p.iv) && p.iv > 0);
    if (usable.length < 2) return null;

    const strikes = usable.map((p) => p.strike);
    const ivs = usable.map((p) => p.iv);
    const minStrike = Math.min(...strikes);
    const maxStrike = Math.max(...strikes);
    const minIv = Math.min(...ivs);
    const maxIv = Math.max(...ivs);
    const ivRange = maxIv - minIv || 0.01;
    const strikeRange = maxStrike - minStrike || 1;

    const x = (strike: number) =>
      PAD_X + ((strike - minStrike) / strikeRange) * (WIDTH - PAD_X * 2);
    // Inverted: higher IV sits higher on the screen.
    const y = (iv: number) => HEIGHT - PAD_Y - ((iv - minIv) / ivRange) * (HEIGHT - PAD_Y * 2);

    const coords: Array<[number, number]> = usable.map((p) => [x(p.strike), y(p.iv)]);
    return {
      path: catmullRomPath(coords),
      area: `${catmullRomPath(coords)} L${coords.at(-1)![0]} ${HEIGHT} L${coords[0]![0]} ${HEIGHT} Z`,
      spotX: spot > 0 ? x(Math.min(Math.max(spot, minStrike), maxStrike)) : null,
      coords,
      minIv,
      maxIv,
    };
  }, [points, spot]);

  useEffect(() => {
    if (pathRef.current) {
      setLength(Math.ceil(pathRef.current.getTotalLength()) || 1200);
    }
  }, [geometry?.path]);

  if (!geometry) {
    return (
      <div
        className="flex h-[84px] items-center text-[color:var(--text-dim)] text-xs"
        aria-label="Skew curve unavailable"
      >
        <span className="mono">awaiting chain data</span>
      </div>
    );
  }

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      preserveAspectRatio="none"
      className="h-[84px] w-full"
      role="img"
      aria-label={`Implied volatility across strikes, ${(geometry.minIv * 100).toFixed(
        1,
      )} to ${(geometry.maxIv * 100).toFixed(1)} vol points`}
    >
      <defs>
        <linearGradient id="skew-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={accent} stopOpacity="0.16" />
          <stop offset="100%" stopColor={accent} stopOpacity="0" />
        </linearGradient>
      </defs>

      <path d={geometry.area} fill="url(#skew-fill)" />

      {geometry.spotX !== null && (
        <line
          x1={geometry.spotX}
          y1={0}
          x2={geometry.spotX}
          y2={HEIGHT}
          stroke="var(--line)"
          strokeWidth={1}
          strokeDasharray="2 3"
        />
      )}

      <path
        key={redrawKey}
        ref={pathRef}
        d={geometry.path}
        fill="none"
        stroke={accent}
        strokeWidth={1.75}
        strokeLinecap="round"
        className="curve-redraw"
        style={
          {
            strokeDasharray: length,
            "--dash": length,
          } as React.CSSProperties
        }
        vectorEffect="non-scaling-stroke"
      />

      {geometry.coords.map(([cx, cy], i) => (
        <circle key={i} cx={cx} cy={cy} r={1.4} fill={accent} opacity={0.5} />
      ))}
    </svg>
  );
}
