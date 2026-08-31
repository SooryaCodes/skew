"use client";

/**
 * The header, reduced to what earns its place:
 * wordmark · desk / positions · health dot · last cycle · theme toggle.
 *
 * Six competing status tokens taught nothing; the armed state, paper-only
 * guarantee, selector health, broker link and market state collapse into one
 * health dot whose tooltip lists the full picture. Verdigris means every
 * subsystem answers; oxide means one does not, and the tooltip names it.
 */

import Link from "next/link";

import { LogoMark } from "@/components/Logo";

import { timeAgo } from "@/lib/format";
import type { SystemStatus } from "@/lib/types";

import { ThemeToggle } from "./ThemeToggle";

interface Props {
  status: SystemStatus | undefined;
  tab: "desk" | "positions";
}

function healthReport(status: SystemStatus | undefined): { ok: boolean; lines: string[] } {
  if (!status) return { ok: false, lines: ["status unavailable — backend unreachable"] };
  const lines = [
    status.broker_connected ? "broker connected" : "BROKER UNREACHABLE",
    status.market_open ? "market open" : "market closed",
    status.auto_execute
      ? status.armed
        ? "armed — selector answering"
        : `NOT ARMED — ${status.selector_error ?? "selector down"}`
      : "standing down (auto-execute off)",
    status.kill_switch ? "KILL SWITCH ENGAGED" : "kill switch off",
    "paper only — no live code path exists",
  ];
  const ok =
    status.broker_connected && (!status.auto_execute || status.armed) && !status.kill_switch;
  return { ok, lines };
}

export function Header({ status, tab }: Props) {
  const health = healthReport(status);

  return (
    <header className="border-b border-[color:var(--line)]">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
        <Link href="/" className="font-display text-[length:var(--fs-md)] leading-none">
          <span className="flex items-center gap-2"><LogoMark size={22} /> SKEW</span>
        </Link>

        <nav className="flex gap-3" aria-label="Views">
          <Link
            href="/desk"
            className="mono t-fast text-[13px] uppercase tracking-wider"
            style={{ color: tab === "desk" ? "var(--text)" : "var(--text-dim)" }}
          >
            desk
          </Link>
          <Link
            href="/positions"
            className="mono t-fast text-[13px] uppercase tracking-wider"
            style={{ color: tab === "positions" ? "var(--text)" : "var(--text-dim)" }}
          >
            positions
          </Link>
        </nav>

        <div className="ml-auto flex items-center gap-4">
          {/* The one connection indicator. Hover for the full report. */}
          <span
            className="flex cursor-default items-center gap-1.5"
            title={health.lines.join("\n")}
            role="status"
            aria-label={health.lines.join("; ")}
          >
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: health.ok ? "var(--verdigris)" : "var(--oxide)" }}
              aria-hidden
            />
            <span className="mono text-[12px] uppercase tracking-wider text-[color:var(--text-dim)]">
              {health.ok ? "all clear" : "attention"}
            </span>
          </span>

          {status?.last_cycle && (
            <span className="mono text-[12px] text-[color:var(--text-dim)]">
              cycle {timeAgo(status.last_cycle)}
            </span>
          )}

          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
