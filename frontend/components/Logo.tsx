/**
 * The SKEW mark: a bold S whose middle stroke is a long diagonal — literally a
 * skewed S. Generated with Higgsfield, cut out, and rebaked over a vector-
 * crisp tile. PNG at 4x display density; the tile color is the brand iris and
 * stays constant across themes, as an app icon should.
 */

export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    /* eslint-disable-next-line @next/next/no-img-element -- exact baked pixels */
    <img
      src={size > 64 ? "/brand/skew-logo-512.png" : "/brand/skew-logo-180.png"}
      alt=""
      width={size}
      height={size}
      aria-hidden
      style={{ display: "block" }}
    />
  );
}

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <span className="flex items-center gap-2.5">
      <LogoMark size={size} />
      <span
        className="font-display tracking-tight"
        style={{ fontSize: Math.round(size * 0.71), letterSpacing: "-0.02em" }}
      >
        SKEW
      </span>
    </span>
  );
}
