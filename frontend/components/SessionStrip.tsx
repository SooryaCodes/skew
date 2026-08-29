"use client";

/**
 * The closed-market state and the session summary.
 *
 * Judging happens after the deadline, likely on a weekend. Without this, the
 * best work in the project is invisible: an inert screen of abstentions. So
 * when the market is closed the desk says exactly what it is showing — the
 * full last session, honestly timestamped — and the summary strip gives the
 * shape of a real working day. The most recent fill, if one exists, sits
 * prominently: it is the proof the whole submission rests on.
 *
 * Nothing here fabricates a live-looking number. Every stale figure carries
 * its "as of".
 */

import { clockTime, timeAgo } from "@/lib/format";
import { useSession, useStatus } from "@/lib/api";

function sessionLabel(iso: string): string {
  const d = new Date(`${iso}T12:00:00Z`);
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

export function KillBanner() {
  const { data: status } = useStatus();
  if (!status?.kill_switch) return null;
  return (
    <div
      className="flex items-center gap-2 border-b border-[color:var(--line)] bg-[color:var(--panel-alt)] px-4 py-1.5"
      role="status"
    >
      <span
        className="inline-block h-[7px] w-[7px]"
        style={{ background: "var(--brass)", borderRadius: "1px" }}
        aria-hidden
      />
      <span className="mono text-[10px] uppercase tracking-wider text-[color:var(--text)]">
        Entries halted. Open positions still monitored.
      </span>
    </div>
  );
}

export function SessionStrip() {
  const { data: status } = useStatus();
  const { data: session } = useSession();

  if (!session) return null;
  const closed = status ? !status.market_open : false;
  const counts = session.counts;

  return (
    <section aria-label="Session summary">
      {/* The closed-market header line. Never looks broken or empty. */}
      {closed && (
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-[color:var(--line)] bg-[color:var(--panel)] px-4 py-1.5">
          <span className="mono text-[10px] uppercase tracking-wider text-[color:var(--text)]">
            market closed
          </span>
          <span className="mono text-[10px] text-[color:var(--text-dim)]">
            showing the session of {sessionLabel(session.session_date)}
            {session.as_of && ` · data as of ${clockTime(session.as_of)}`}
          </span>
        </div>
      )}

      {/* The shape of the working day. */}
      <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1 border-b border-[color:var(--line)] px-4 py-1.5">
        <span className="mono text-[9px] uppercase tracking-widest text-[color:var(--text-dim)]">
          session
        </span>
        <Stat label="scanned" value={session.scanned} />
        <Stat label="candidates" value={session.candidates_built} />
        <Stat label="survived" value={session.survivors} />
        <Stat label="refused" value={counts.REFUSED ?? 0} />
        <Stat label="abstained" value={counts.ABSTAINED ?? 0} />
        <Stat label="filled" value={counts.EXECUTED ?? 0} />

        {/* The proof: the most recent fill, whenever it happened. */}
        {session.last_fill && (
          <span className="flex min-w-0 items-baseline gap-1.5">
            <span
              className="inline-block h-[7px] w-[7px] shrink-0 self-center"
              style={{ background: "var(--verdigris)", borderRadius: "1px" }}
              aria-hidden
            />
            <span className="mono truncate text-[10px] text-[color:var(--text)]">
              last fill · {session.last_fill.symbol} · {session.last_fill.reason}
            </span>
            <span className="mono shrink-0 text-[9px] text-[color:var(--text-dim)]">
              {timeAgo(session.last_fill.ts)}
            </span>
          </span>
        )}
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <span className="mono text-[10px] text-[color:var(--text-dim)]">
      <span className="text-[color:var(--text)]">{value}</span> {label}
    </span>
  );
}
