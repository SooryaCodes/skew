"use client";

/**
 * The header. The skew curve is its spine, not a widget inside it.
 */

import Link from "next/link";

import { timeAgo } from "@/lib/format";
import type { SystemStatus } from "@/lib/types";

import { ThemeToggle } from "./ThemeToggle";

interface Props {
  status: SystemStatus | undefined;
  tab: "desk" | "positions";
}

function Dot({ on, label }: { on: boolean; label: string }) {
  return (
    <span className="mono inline-flex items-center gap-1 text-[10px] text-[color:var(--text-dim)]">
      <span
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ background: on ? "var(--steel)" : "var(--line)" }}
        aria-hidden
      />
      {label}
    </span>
  );
}

export function Header({ status, tab }: Props) {
  return (
    // The full-bleed curve is gone: stretched across a header, twenty points
    // of vertical range flatten into a squiggle. The skew now lives as a
    // properly-scaled instrument beside the dials, where it shows something.
    <header className="relative border-b border-[color:var(--line)]">
      <div className="relative flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
        <Link href="/" className="font-display text-[length:var(--fs-md)] leading-none">
          SKEW
        </Link>

        <nav className="flex gap-3" aria-label="Views">
          <Link
            href="/"
            className="mono t-fast text-[11px] uppercase tracking-wider"
            style={{ color: tab === "desk" ? "var(--text)" : "var(--text-dim)" }}
          >
            desk
          </Link>
          <Link
            href="/positions"
            className="mono t-fast text-[11px] uppercase tracking-wider"
            style={{ color: tab === "positions" ? "var(--text)" : "var(--text-dim)" }}
          >
            positions
          </Link>
        </nav>

        <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1">
          <Dot on={status?.broker_connected ?? false} label="broker" />
          <Dot on={status?.market_open ?? false} label={status?.market_open ? "open" : "closed"} />
          {status?.kill_switch && (
            <span className="flex items-center gap-1.5">
              <span
                className="inline-block h-[7px] w-[7px]"
                style={{ background: "var(--brass)", borderRadius: "1px" }}
                aria-hidden
              />
              <span className="mono text-[10px] uppercase tracking-wider text-[color:var(--text)]">
                kill switch engaged
              </span>
            </span>
          )}
          {/* "armed" comes from the server, which gates it on a startup
              preflight call to the selector — the desk never claims it can
              trade on configuration alone. */}
          {status?.auto_execute && !status.armed && (
            <span className="flex items-center gap-1.5" title={status.selector_error ?? undefined}>
              <span
                className="inline-block h-[7px] w-[7px]"
                style={{ background: "var(--brass)", borderRadius: "1px" }}
                aria-hidden
              />
              <span className="mono text-[10px] uppercase tracking-wider text-[color:var(--text)]">
                selector down — not armed
              </span>
            </span>
          )}
          {status?.armed && (
            <span className="mono text-[10px] uppercase tracking-wider text-[color:var(--text-dim)]">
              armed
            </span>
          )}
          <span className="mono text-[10px] uppercase tracking-wider text-[color:var(--text-dim)]">
            paper only
          </span>
          {status?.last_cycle && (
            <span className="mono text-[10px] text-[color:var(--text-dim)]">
              cycle {timeAgo(status.last_cycle)}
            </span>
          )}
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
