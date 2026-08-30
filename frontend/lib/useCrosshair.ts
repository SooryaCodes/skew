"use client";

/**
 * Shared crosshair state for the three instruments.
 *
 * Converts pointer position to viewBox coordinates and leaves snapping to the
 * chart, which knows its own data. Hover moves it, tap places it (touch),
 * leave clears it — the chart then falls back to its default readout (ATM /
 * current), so the corner is never empty. Real data only: the caller snaps to
 * the nearest actual point, never interpolates.
 */

import { useCallback, useRef, useState } from "react";

export function useCrosshair(viewBoxWidth: number) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [pointerX, setPointerX] = useState<number | null>(null);

  const place = useCallback(
    (clientX: number) => {
      const svg = svgRef.current;
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      if (rect.width <= 0) return;
      setPointerX(((clientX - rect.left) / rect.width) * viewBoxWidth);
    },
    [viewBoxWidth],
  );

  const handlers = {
    onPointerMove: (e: React.PointerEvent) => place(e.clientX),
    onPointerDown: (e: React.PointerEvent) => place(e.clientX),
    onPointerLeave: () => setPointerX(null),
  };

  return { svgRef, pointerX, handlers };
}

/** Index of the point whose x is nearest the pointer — snapping, not lerping. */
export function nearestIndex(xs: number[], pointerX: number): number {
  let best = 0;
  let bestDist = Number.POSITIVE_INFINITY;
  xs.forEach((x, i) => {
    const d = Math.abs(x - pointerX);
    if (d < bestDist) {
      bestDist = d;
      best = i;
    }
  });
  return best;
}
