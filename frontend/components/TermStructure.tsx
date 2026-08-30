"use client";

/**
 * The term structure — ATM implied vol against days to expiry.
 *
 * Upward slope is contango: the calm state, more uncertainty priced into more
 * time. When the curve inverts the market is frightened of something imminent,
 * and the stroke flips to --oxide — sanctioned here because backwardation IS
 * the hard gate: the desk never sells premium into an inverted curve.
 */

import { useMemo } from "react";

import type { TermPoint } from "@/lib/types";
import { nearestIndex, useCrosshair } from "@/lib/useCrosshair";

const W = 280;
const H = 100;
const PAD_L = 28;
const PAD_R = 10;
const PAD_T = 8;
const PAD_B = 16;

interface Props {
  points: TermPoint[];
  /** far minus near, annualised decimal. Negative = inverted. */
  slope: number;
}

export function TermStructure({ points, slope }: Props) {
  const inverted = slope < -0.005;
  const { svgRef, pointerX, handlers } = useCrosshair(W);

  const geo = useMemo(() => {
    const usable = points
      .filter((p) => p.dte >= 5 && p.dte <= 95 && p.iv_atm > 0)
      .sort((a, b) => a.dte - b.dte);
    if (usable.length < 2) return null;

    const minD = usable[0]!.dte;
    const maxD = usable.at(-1)!.dte;
    const ivs = usable.map((p) => p.iv_atm);
    const minV = Math.min(...ivs) * 0.96;
    const maxV = Math.max(...ivs) * 1.04;

    const x = (d: number) => PAD_L + ((d - minD) / (maxD - minD || 1)) * (W - PAD_L - PAD_R);
    const y = (v: number) => H - PAD_B - ((v - minV) / (maxV - minV || 1)) * (H - PAD_T - PAD_B);

    return {
      usable,
      line: usable.map((p) => `${x(p.dte)},${y(p.iv_atm)}`).join(" "),
      dots: usable.map((p) => ({ cx: x(p.dte), cy: y(p.iv_atm), dte: p.dte, iv: p.iv_atm })),
      minV,
      maxV,
    };
  }, [points]);

  if (!geo) {
    return (
      <p className="mono text-[10px] text-[color:var(--text-dim)]">
        term structure unavailable — fewer than two usable expiries
      </p>
    );
  }

  const stroke = inverted ? "var(--oxide)" : "var(--steel)";

  // Crosshair: nearest real expiry; the front expiry is the resting readout.
  const hoverIndex =
    pointerX === null ? 0 : nearestIndex(geo.dots.map((d) => d.cx), pointerX);
  const hovered = geo.dots[hoverIndex]!;
  const isDefault = pointerX === null;

  return (
    <svg
      ref={svgRef}
      {...handlers}
      viewBox={`0 0 ${W} ${H}`}
      className="h-auto w-full touch-none max-w-[280px]"
      role="img"
      aria-label={`ATM implied vol by days to expiry, ${inverted ? "inverted — backwardation" : "upward — contango"}`}
    >
      <line x1={PAD_L} y1={H - PAD_B} x2={W - PAD_R} y2={H - PAD_B} stroke="var(--line)" />
      <text x={PAD_L - 4} y={PAD_T + 8} textAnchor="end" className="mono" fontSize={8} fill="var(--text-dim)">
        {(geo.maxV * 100).toFixed(0)}
      </text>
      <text x={PAD_L - 4} y={H - PAD_B} textAnchor="end" className="mono" fontSize={8} fill="var(--text-dim)">
        {(geo.minV * 100).toFixed(0)}
      </text>

      <polyline points={geo.line} fill="none" stroke={stroke} strokeWidth={1.5} />
      {geo.dots.map((d) => (
        <circle key={d.dte} cx={d.cx} cy={d.cy} r={2} fill={stroke} />
      ))}

      {/* crosshair */}
      {!isDefault && (
        <line
          x1={hovered.cx}
          y1={PAD_T}
          x2={hovered.cx}
          y2={H - PAD_B}
          stroke="var(--text-faint)"
          strokeWidth={0.75}
        />
      )}
      <circle cx={hovered.cx} cy={hovered.cy} r={3} fill={stroke} />
      <text
        x={W - PAD_R}
        y={PAD_T + 2}
        textAnchor="end"
        className="mono"
        fontSize={7.5}
        fill="var(--text-dim)"
      >
        {isDefault ? "front · " : ""}
        {hovered.dte}d · iv {(hovered.iv * 100).toFixed(1)}
      </text>

      {[geo.dots[0]!, geo.dots.at(-1)!].map((d, i) => (
        <text
          key={i}
          x={d.cx}
          y={H - 5}
          textAnchor={i === 0 ? "start" : "end"}
          className="mono"
          fontSize={8}
          fill="var(--text-dim)"
        >
          {d.dte}d
        </text>
      ))}
    </svg>
  );
}
