"use client";

/**
 * The header. The skew curve is its spine, not a widget inside it.
 */

import Link from "next/link";

import { regimeColor, timeAgo } from "@/lib/format";
import type { SystemStatus, VolState } from "@/lib/types";

import { SkewCurve } from "./SkewCurve";

interface Props {
  focused: VolState | undefined;
  status: SystemStatus | undefined;
  tab: "desk" | "positions";
}

function Dot({ on, label }: { on: boolean; label: string }) {
  return (
    <span className="mono inline-flex items-center gap-1 text-[10px] text-[color:var(--muted)]">
      <span
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ background: on ? "var(--cheap)" : "var(--line)" }}
        aria-hidden
      />
      {label}
    </span>
  );
}

export function Header({ focused, status, tab }: Props) {
  const accent = focused ? regimeColor(focused.regime) : "var(--muted)";

  return (
    // min-height so the 72px curve has room to be the spine rather than a
    // clipped sliver; overflow-hidden so it never bleeds into the columns below.
    <header className="relative min-h-[6rem] overflow-hidden border-b border-[color:var(--line)]">
      {/* Ambient, always moving. The thesis before a word is read. */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 opacity-80">
        <SkewCurve
          points={focused?.skew_curve ?? []}
          spot={focused?.spot ?? 0}
          accent={accent}
          redrawKey={`${focused?.symbol ?? "none"}-${focused?.as_of ?? ""}`}
        />
      </div>

      <div className="relative flex flex-wrap items-center gap-x-6 gap-y-2 px-4 pt-3 pb-8">
        <Link href="/" className="font-display text-[length:var(--fs-md)] leading-none">
          SKEW
        </Link>

        <nav className="flex gap-3" aria-label="Views">
          <Link
            href="/"
            className="mono t-fast text-[11px] uppercase tracking-wider"
            style={{ color: tab === "desk" ? "var(--text)" : "var(--muted)" }}
          >
            desk
          </Link>
          <Link
            href="/positions"
            className="mono t-fast text-[11px] uppercase tracking-wider"
            style={{ color: tab === "positions" ? "var(--text)" : "var(--muted)" }}
          >
            positions
          </Link>
        </nav>

        <p className="mono hidden text-[10px] text-[color:var(--muted)] lg:block">
          implied volatility across strikes
        </p>

        <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1">
          <Dot on={status?.broker_connected ?? false} label="broker" />
          <Dot on={status?.market_open ?? false} label={status?.market_open ? "open" : "closed"} />
          {status?.kill_switch && (
            <span
              className="mono text-[10px] uppercase tracking-wider"
              style={{ color: "var(--rich)" }}
            >
              kill switch engaged
            </span>
          )}
          <span className="mono text-[10px] uppercase tracking-wider text-[color:var(--muted)]">
            paper only
          </span>
          {status?.last_cycle && (
            <span className="mono text-[10px] text-[color:var(--muted)]">
              cycle {timeAgo(status.last_cycle)}
            </span>
          )}
        </div>
      </div>
    </header>
  );
}
