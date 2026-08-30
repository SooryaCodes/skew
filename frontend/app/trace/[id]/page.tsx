"use client";

/**
 * Deep-linkable decision trace: /trace/<decision_id>.
 *
 * The whole claim of this project is that the decision process is inspectable.
 * This page makes it literally so — one URL per decision, droppable into the
 * submission and the video, rendering the recorded reasoning chain end to end.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR from "swr";

import { Header } from "@/components/Header";
import { TracePanel } from "@/components/TracePanel";
import { API_BASE, useStatus } from "@/lib/api";
import { clockTime, timeAgo } from "@/lib/format";
import type { Decision } from "@/lib/types";

const ACTION_COLOR: Record<string, string> = {
  EXECUTED: "var(--verdigris)",
  REFUSED: "var(--oxide)",
  ABSTAINED: "var(--line)",
};

export default function TracePage() {
  const params = useParams<{ id: string }>();
  const { data: status } = useStatus();
  const { data: decision, error } = useSWR<Decision>(
    params?.id ? `/api/decision/${params.id}` : null,
    async (path: string) => {
      const response = await fetch(`${API_BASE}${path}`);
      if (!response.ok) throw new Error(String(response.status));
      return (await response.json()) as Decision;
    },
  );

  return (
    <div className="flex min-h-screen flex-col">
      <Header status={status} tab="desk" />

      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-8">
        <div className="mb-6 flex items-baseline justify-between gap-4">
          <p className="mono text-[10px] uppercase tracking-widest text-[color:var(--text-dim)]">
            decision trace
          </p>
          <Link
            href="/desk"
            className="mono t-fast text-[10px] uppercase tracking-wider text-[color:var(--text-dim)] hover:text-[color:var(--text)]"
          >
            ← back to the desk
          </Link>
        </div>

        {error ? (
          <p className="text-sm text-[color:var(--text-dim)]">
            No decision with that id. Traces link from the audit log on the desk.
          </p>
        ) : !decision ? (
          <p className="mono text-[11px] text-[color:var(--text-dim)]">loading trace…</p>
        ) : (
          <>
            <header className="mb-8">
              <div className="flex flex-wrap items-center gap-3">
                <span
                  className="inline-block h-[8px] w-[8px]"
                  style={{
                    background: ACTION_COLOR[decision.action] ?? "var(--line)",
                    borderRadius: "1px",
                  }}
                  aria-hidden
                />
                <h1 className="font-display text-[length:var(--fs-lg)] leading-none">
                  {decision.symbol ?? "—"}
                </h1>
                <span className="mono text-[11px] uppercase tracking-wider text-[color:var(--text)]">
                  {decision.action.toLowerCase()}
                </span>
                <span className="mono text-[10px] text-[color:var(--text-dim)]">
                  {clockTime(decision.ts)} · {timeAgo(decision.ts)} · tier {decision.risk_tier}
                </span>
              </div>
              <p className="mt-3 max-w-2xl text-[13px] leading-relaxed text-[color:var(--text)]">
                {decision.reason}
              </p>
            </header>

            <TracePanel decision={decision} />

            <p className="mono mt-6 border-t border-[color:var(--line)] pt-4 text-[10px] leading-relaxed text-[color:var(--text-dim)]">
              Every value above was recorded when this decision was made — nothing
              is recomputed for display. Deterministic gates decided what was
              possible; the bounded selector could only choose among what
              survived, or abstain.
            </p>
          </>
        )}
      </main>
    </div>
  );
}
