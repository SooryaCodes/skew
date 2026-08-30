"use client";

/**
 * The hero — the volatility surface itself, drawn from live chain data.
 *
 * One skew curve per expiry, near expiries at the front in --brass, far ones
 * receding into --steel: the whole thesis (what movement costs, at every
 * tenor) as the opening image. Curves draw in far-to-near over ~1.2s, the
 * finished surface breathes ±3px on a 12s cycle, and the pointer applies a
 * damped parallax — near curves shift more than far ones, which is what makes
 * it read as an object instead of a picture.
 *
 * Honesty rule: if the chain is unreachable there is no surface — a quiet
 * caption says so. Nothing here is synthesised.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import { useSurface } from "@/lib/api";
import { prefersReducedMotion } from "@/lib/useInView";

const W = 1000;
const H = 640;

interface Props {
  symbol?: string;
  /** 0 → full hero; 1 → flattened and shrunk into the next section's margin. */
  progress: number;
}

export function VolatilitySurface({ symbol = "SPY", progress }: Props) {
  const { data } = useSurface(symbol);
  const [parallax, setParallax] = useState(0);
  const parallaxTarget = useRef(0);
  const reduced = useRef(false);

  useEffect(() => {
    reduced.current = prefersReducedMotion();
    if (reduced.current) return;
    let raf = 0;
    const onMove = (e: PointerEvent) => {
      parallaxTarget.current = e.clientX / window.innerWidth - 0.5;
    };
    const tick = () => {
      // Damped follow — the surface trails the pointer, never tracks it.
      setParallax((v) => v + (parallaxTarget.current - v) * 0.05);
      raf = requestAnimationFrame(tick);
    };
    window.addEventListener("pointermove", onMove);
    raf = requestAnimationFrame(tick);
    return () => {
      window.removeEventListener("pointermove", onMove);
      cancelAnimationFrame(raf);
    };
  }, []);

  const curves = useMemo(() => {
    const slices = data?.slices ?? [];
    if (slices.length < 3) return null;
    // Farthest expiry first: drawn first, sits behind, starts the draw-in.
    const ordered = [...slices].sort((a, b) => b.dte - a.dte);
    const ivs = ordered.flatMap((s) => s.points.map((p) => p.iv));
    const ivMin = Math.min(...ivs);
    const ivMax = Math.max(...ivs);
    const n = ordered.length;

    return ordered.map((slice, i) => {
      const t = n === 1 ? 1 : i / (n - 1); // 0 = farthest, 1 = front month
      // Pushed low: the type owns the upper-left, the surface sweeps beneath.
      const rowY = 210 + t * 360;
      const shear = (1 - t) * 130;
      const inset = (1 - t) * 60;
      const pts = [...slice.points]
        .sort((a, b) => a.moneyness - b.moneyness)
        .map((p) => {
          const mx = Math.min(1.12, Math.max(0.88, p.moneyness));
          const x = 40 + shear + ((mx - 0.88) / 0.24) * (W - 120 - inset - shear);
          const amp = ((p.iv - ivMin) / (ivMax - ivMin || 1)) * 170;
          return `${x.toFixed(1)},${(rowY - amp).toFixed(1)}`;
        })
        .join(" ");
      return {
        key: slice.dte,
        pts,
        t,
        stroke: `color-mix(in srgb, var(--brass) ${Math.round(t * 100)}%, var(--steel))`,
        width: 0.9 + t * 0.7,
        opacity: 0.28 + t * 0.6,
        delaySec: (i / n) * 1.2,
      };
    });
  }, [data]);

  if (!curves) {
    return (
      <p className="mono absolute bottom-6 right-6 text-[9px] uppercase tracking-wider text-[color:var(--text-dim)]">
        surface unavailable — this hero only draws the live chain
      </p>
    );
  }

  const p = Math.min(1, Math.max(0, progress));

  return (
    <div
      aria-hidden
      className="absolute inset-0"
      style={{
        // The scroll choreography: the surface flattens and shrinks toward the
        // top-left, ending as a margin object beside section two.
        transform: `translate(${(-p * 26).toFixed(2)}%, ${(-p * 22).toFixed(2)}%) scale(${(1 - p * 0.58).toFixed(3)})`,
        transformOrigin: "22% 32%",
      }}
    >
      <div className={p < 0.05 ? "surface-breathe h-full w-full" : "h-full w-full"}>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="h-full w-full"
          preserveAspectRatio="xMidYMid slice"
        >
          {curves.map((c) => (
            <polyline
              key={c.key}
              points={c.pts}
              pathLength={1}
              fill="none"
              stroke={c.stroke}
              strokeWidth={c.width}
              strokeDasharray={1}
              className="curve-in"
              style={{
                // Parallax by depth: front curves travel further than far ones.
                transform: `translateX(${(parallax * (6 + c.t * 16)).toFixed(2)}px)`,
                // Flatten: far curves thin out first as the surface recedes.
                opacity: c.opacity * (c.t > 0.85 ? 1 : 1 - p * 0.9),
                animationDelay: `${c.delaySec.toFixed(2)}s`,
              }}
            />
          ))}
        </svg>
      </div>
    </div>
  );
}
