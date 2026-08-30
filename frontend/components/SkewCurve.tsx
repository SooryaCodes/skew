"use client";

/**
 * The skew curve — IV against strike for the front expiry.
 *
 * Fixed frame, never full-bleed: stretched across a header, twenty points of
 * vertical range flatten into a squiggle and the chart shows nothing. Here the
 * Y axis is scaled to the data range so the curvature — the thing the product
 * is named after — is actually visible.
 *
 * The front expiry draws in --brass at 1.5px. The next two expiries ride
 * behind it as ghosts in --steel-dim, so the surface reads as having depth.
 * ATM is a hairline to the axis; the wings are marked at ±2σ of what this
 * underlying actually moves over the front expiry's life.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import type { SkewSlice } from "@/lib/types";
import { nearestIndex, useCrosshair } from "@/lib/useCrosshair";

const W = 420;
const H = 120;
const PAD_L = 30;
const PAD_R = 10;
const PAD_T = 8;
const PAD_B = 18;

interface Props {
  slices: SkewSlice[];
  spot: number;
  /** Annualised 20d realized vol — sizes the ±2σ wing markers. */
  rv20: number;
  redrawKey?: string;
  /** The landing hero draws it large; the desk instrument stays capped at 420. */
  large?: boolean;
}

function smoothPath(coords: Array<[number, number]>): string {
  if (coords.length === 0) return "";
  if (coords.length < 3) {
    return coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x} ${y}`).join(" ");
  }
  let d = `M${coords[0]![0]} ${coords[0]![1]}`;
  for (let i = 0; i < coords.length - 1; i += 1) {
    const p0 = coords[Math.max(0, i - 1)]!;
    const p1 = coords[i]!;
    const p2 = coords[i + 1]!;
    const p3 = coords[Math.min(coords.length - 1, i + 2)]!;
    d += ` C${p1[0] + (p2[0] - p0[0]) / 6} ${p1[1] + (p2[1] - p0[1]) / 6} ${
      p2[0] - (p3[0] - p1[0]) / 6
    } ${p2[1] - (p3[1] - p1[1]) / 6} ${p2[0]} ${p2[1]}`;
  }
  return d;
}

export function SkewCurve({ slices, spot, rv20, redrawKey, large = false }: Props) {
  const pathRef = useRef<SVGPathElement | null>(null);
  const [dash, setDash] = useState(900);
  const { svgRef, pointerX, handlers } = useCrosshair(W);

  const geo = useMemo(() => {
    const front = slices[0];
    if (!front || front.points.length < 3) return null;

    const all = slices.flatMap((s) => s.points).filter((p) => p.iv > 0);
    const strikes = front.points.map((p) => p.strike);
    const minStrike = Math.min(...strikes);
    const maxStrike = Math.max(...strikes);
    const ivs = all.map((p) => p.iv);
    // Y scaled to the DATA range — this is the whole fix.
    const minIv = Math.min(...ivs);
    const maxIv = Math.max(...ivs);
    const ivPad = (maxIv - minIv || 0.01) * 0.08;

    const x = (k: number) =>
      PAD_L + ((k - minStrike) / (maxStrike - minStrike || 1)) * (W - PAD_L - PAD_R);
    const y = (iv: number) =>
      H -
      PAD_B -
      ((iv - (minIv - ivPad)) / (maxIv - minIv + 2 * ivPad || 1)) * (H - PAD_T - PAD_B);

    // The RENDERED line is lightly smoothed (3-point moving average) — the
    // backend already filtered illiquid strikes, and this removes the residual
    // quote noise. The crosshair snaps to the RAW filtered points, so every
    // number a reader can summon is a real quote, never the smoothing.
    const smoothIvs = (values: number[]) =>
      values.map((_v, i) => {
        const lo = Math.max(0, i - 1);
        const hi = Math.min(values.length - 1, i + 1);
        let sum = 0;
        for (let j = lo; j <= hi; j += 1) sum += values[j]!;
        return sum / (hi - lo + 1);
      });

    const toPath = (s: SkewSlice) => {
      const inRange = s.points.filter((p) => p.strike >= minStrike && p.strike <= maxStrike);
      const smoothed = smoothIvs(inRange.map((p) => p.iv));
      return smoothPath(inRange.map((p, i) => [x(p.strike), y(smoothed[i]!)] as [number, number]));
    };

    // One-sigma move over the front expiry's life: rv × √(dte/365), in dollars.
    const sigma = spot * rv20 * Math.sqrt(Math.max(front.dte, 1) / 365);
    const wing = (n: number) => {
      const k = spot + n * sigma;
      return k >= minStrike && k <= maxStrike ? x(k) : null;
    };

    // Every real front-expiry point, for the crosshair to snap to.
    const pts = [...front.points]
      .sort((a, b) => a.strike - b.strike)
      .map((point) => ({
        px: x(point.strike),
        py: y(point.iv),
        strike: point.strike,
        iv: point.iv,
        delta: point.delta,
      }));

    return {
      pts,
      front: toPath(front),
      ghosts: slices.slice(1).map(toPath),
      spotX: spot >= minStrike && spot <= maxStrike ? x(spot) : null,
      wings: [
        { label: "−2σ", px: wing(-2) },
        { label: "+2σ", px: wing(2) },
      ].filter((w): w is { label: string; px: number } => w.px !== null),
      minIv,
      maxIv,
      dte: front.dte,
    };
  }, [slices, spot, rv20]);

  useEffect(() => {
    if (pathRef.current) setDash(Math.ceil(pathRef.current.getTotalLength()) || 900);
  }, [geo?.front]);

  if (!geo) {
    return (
      <p className="mono text-[10px] text-[color:var(--text-dim)]">
        skew unavailable — fewer than three usable strikes on the front expiry
      </p>
    );
  }

  // Crosshair: snap to the nearest REAL strike; default to ATM so the corner
  // readout is never empty.
  const atmIndex = nearestIndex(geo.pts.map((pt) => pt.px), geo.spotX ?? W / 2);
  const hoverIndex = pointerX === null ? atmIndex : nearestIndex(geo.pts.map((pt) => pt.px), pointerX);
  const hovered = geo.pts[hoverIndex]!;
  const isDefault = pointerX === null;

  return (
    <svg
      ref={svgRef}
      {...handlers}
      viewBox={`0 0 ${W} ${H}`}
      className={`h-auto w-full touch-none ${large ? "max-w-[760px]" : "max-w-[420px]"}`}
      role="img"
      aria-label={`Implied volatility across strikes, ${(geo.minIv * 100).toFixed(1)} to ${(
        geo.maxIv * 100
      ).toFixed(1)} vol points, front expiry ${geo.dte} days`}
    >
      {/* frame */}
      <line x1={PAD_L} y1={H - PAD_B} x2={W - PAD_R} y2={H - PAD_B} stroke="var(--line)" />
      <text
        x={PAD_L - 4}
        y={PAD_T + 8}
        textAnchor="end"
        className="mono"
        fontSize={8}
        fill="var(--text-dim)"
      >
        {(geo.maxIv * 100).toFixed(0)}
      </text>
      <text
        x={PAD_L - 4}
        y={H - PAD_B}
        textAnchor="end"
        className="mono"
        fontSize={8}
        fill="var(--text-dim)"
      >
        {(geo.minIv * 100).toFixed(0)}
      </text>

      {/* ghosts: the next two expiries, faint steel */}
      {geo.ghosts.map((d, i) => (
        <path
          key={i}
          d={d}
          fill="none"
          stroke="var(--steel-dim)"
          strokeWidth={1}
          opacity={i === 0 ? 0.7 : 0.45}
        />
      ))}

      {/* ATM hairline to the axis */}
      {geo.spotX !== null && (
        <>
          <line
            x1={geo.spotX}
            y1={PAD_T}
            x2={geo.spotX}
            y2={H - PAD_B}
            stroke="var(--line)"
            strokeDasharray="2 3"
          />
          <text
            x={geo.spotX}
            y={H - 7}
            textAnchor="middle"
            className="mono"
            fontSize={8}
            fill="var(--text-dim)"
          >
            atm
          </text>
        </>
      )}

      {/* ±2σ wing markers */}
      {geo.wings.map((w) => (
        <g key={w.label}>
          <line x1={w.px} y1={H - PAD_B} x2={w.px} y2={H - PAD_B + 4} stroke="var(--text-dim)" />
          <text
            x={w.px}
            y={H - 7}
            textAnchor="middle"
            className="mono"
            fontSize={8}
            fill="var(--text-dim)"
          >
            {w.label}
          </text>
        </g>
      ))}

      {/* the front expiry, brass */}
      <path
        key={redrawKey}
        ref={pathRef}
        d={geo.front}
        fill="none"
        stroke="var(--brass)"
        strokeWidth={1.5}
        strokeLinecap="round"
        className="curve-redraw"
        style={{ strokeDasharray: dash, "--dash": dash } as React.CSSProperties}
      />

      {/* crosshair — hairline snapped to the nearest real strike */}
      {!isDefault && (
        <line
          x1={hovered.px}
          y1={PAD_T}
          x2={hovered.px}
          y2={H - PAD_B}
          stroke="var(--text-faint)"
          strokeWidth={0.75}
        />
      )}
      <circle cx={hovered.px} cy={hovered.py} r={2.5} fill="var(--brass)" />
      {/* readout pinned to the corner, never a tooltip over the data */}
      <text
        x={W - PAD_R}
        y={PAD_T + 2}
        textAnchor="end"
        className="mono"
        fontSize={7.5}
        fill="var(--text-dim)"
      >
        {isDefault ? "atm · " : ""}
        strike {hovered.strike % 1 === 0 ? hovered.strike : hovered.strike.toFixed(2)} · iv{" "}
        {(hovered.iv * 100).toFixed(1)}
        {hovered.delta !== null ? ` · Δ ${hovered.delta.toFixed(2)}` : ""}
      </text>
    </svg>
  );
}
