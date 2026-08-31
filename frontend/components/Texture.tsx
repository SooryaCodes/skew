"use client";

/**
 * Film grain, back by request — coarser than the original so it reads as
 * texture rather than compression noise, at 5-6% where the old pass sat at 3%.
 * Neutral by construction: turn the colour off and the depth survives.
 */

export function Texture() {
  return (
    <svg
      aria-hidden
      className="pointer-events-none fixed inset-0 z-50 h-full w-full"
      style={{ opacity: "var(--grain-opacity, 0.055)" }}
    >
      <filter id="skew-grain">
        <feTurbulence type="fractalNoise" baseFrequency="0.55" numOctaves="2" stitchTiles="stitch" />
        <feColorMatrix type="saturate" values="0" />
      </filter>
      <rect width="100%" height="100%" filter="url(#skew-grain)" />
    </svg>
  );
}
