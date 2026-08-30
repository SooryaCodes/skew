"use client";

/**
 * A 60×24 sparkline of the front expiry's skew — the shape of the smile as a
 * glyph. Stroke only, in the regime's metal: at 1px this is a marker, not
 * text, so the metals are legitimate here.
 */

import type { SkewSlice } from "@/lib/types";

interface Props {
  slices: SkewSlice[];
  color: string;
}

export function Sparkline({ slices, color }: Props) {
  const front = slices[0];
  if (!front || front.points.length < 4) return null;
  const pts = [...front.points].sort((a, b) => a.strike - b.strike);
  const ivs = pts.map((p) => p.iv);
  const min = Math.min(...ivs);
  const max = Math.max(...ivs);
  const line = pts
    .map((p, i) => {
      const x = 1 + (i / (pts.length - 1)) * 58;
      const y = 21 - ((p.iv - min) / (max - min || 1)) * 18;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg viewBox="0 0 60 24" width={60} height={24} aria-hidden>
      <polyline points={line} fill="none" stroke={color} strokeWidth={1} />
    </svg>
  );
}
