"use client";

/**
 * The page texture: film grain over everything at ~3%, a 1px --line-soft grid
 * behind everything at ~4%. No gradients anywhere — this is what stands in
 * for "depth" on a page that refuses glow.
 */

export function Texture() {
  return (
    <>
      <div aria-hidden className="paper-grid pointer-events-none fixed inset-0 z-0" />
      <svg aria-hidden className="pointer-events-none fixed inset-0 z-50 h-full w-full" style={{ opacity: 0.03 }}>
        <filter id="skew-grain">
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch" />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width="100%" height="100%" filter="url(#skew-grain)" />
      </svg>
    </>
  );
}
