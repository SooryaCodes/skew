/**
 * Number formatting.
 *
 * Two rules from docs/03-DESIGN-SYSTEM.md, applied here so they cannot drift:
 *
 * - Every number is mono with tabular figures. Prices that jitter horizontally
 *   as digits change look amateur instantly to anyone who has used a real
 *   trading tool.
 * - Anything that can be negative carries an explicit sign, always.
 *
 * Volatility crosses the wire as an annualised decimal (0.241). It is converted
 * to vol points for display in exactly one place — `vol()` below — so the
 * backend's maths path never has to think about presentation.
 */

/** 0.241 -> "24.1". The one conversion between the wire format and the screen. */
export function vol(value: number, digits = 1): string {
  return (value * 100).toFixed(digits);
}

/** 0.142 -> "+14.2". Always signed: VRP is meaningless without its direction. */
export function volPoints(value: number, digits = 1): string {
  const points = value * 100;
  return `${points >= 0 ? "+" : "−"}${Math.abs(points).toFixed(digits)}`;
}

/** Signed dollars with a real minus sign, not a hyphen. */
export function money(value: number, digits = 2): string {
  const sign = value < 0 ? "−" : "+";
  return `${sign}$${Math.abs(value).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

/** Unsigned dollars, for quantities that cannot be negative (max loss, budget). */
export function dollars(value: number, digits = 0): string {
  return `$${Math.abs(value).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

export function pct(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function num(value: number, digits = 2): string {
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function signed(value: number, digits = 2): string {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(digits)}`;
}

export function compactCount(value: number): string {
  return value.toLocaleString("en-US");
}

/** "SPY260918P00770000" -> "SPY 18 SEP 26 770 P". Mono, uppercase, never wrapped. */
export function contractLabel(symbol: string): string {
  const match = /^([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$/.exec(symbol.toUpperCase());
  if (!match) return symbol.toUpperCase();
  const [, root, yy, mm, dd, right, strikeRaw] = match;
  const months = [
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
  ];
  const month = months[Number(mm) - 1] ?? mm;
  const strike = Number(strikeRaw) / 1000;
  return `${root} ${dd} ${month} ${yy} ${strike % 1 === 0 ? strike : strike.toFixed(2)} ${right}`;
}

export function structureLabel(kind: string): string {
  return kind
    .split("_")
    .map((word) => word.charAt(0) + word.slice(1).toLowerCase())
    .join(" ");
}

export function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/**
 * The colour a regime carries.
 *
 * Amber for expensive volatility is a nod to phosphor trading terminals and
 * reads as heat — the market is hot, fear is priced in. Cool blue reads as calm.
 * Anyone looking at the screen understands the temperature before reading a
 * number.
 *
 * Note what is absent: `--breach` red. It appears nowhere except a failed gate.
 */
export function regimeColor(regime: string): string {
  if (regime === "SELL_VOL") return "var(--rich)";
  if (regime === "BUY_VOL") return "var(--cheap)";
  return "var(--muted)";
}

export function regimeLabel(regime: string): string {
  if (regime === "SELL_VOL") return "vol rich";
  if (regime === "BUY_VOL") return "vol cheap";
  return "abstain";
}
