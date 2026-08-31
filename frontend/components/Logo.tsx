/**
 * The SKEW mark: the volatility smile itself — left wing high (downside
 * protection is bid), dipping at the money, recovering lower on the right.
 * The product's name drawn as its own instrument. Pure SVG: crisp at 16px in
 * a favicon and at 128px in a hero.
 */

export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden
      style={{ borderRadius: Math.max(6, size * 0.28) }}
    >
      <rect width="32" height="32" rx="9" fill="var(--accent)" />
      <path
        d="M6 10.5 C 10 21, 15 23.5, 19 21 C 22.5 18.8, 24.5 16.5, 26 14.5"
        stroke="#fff"
        strokeWidth="3"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
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
