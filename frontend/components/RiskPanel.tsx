"use client";

/**
 * The earned risk authority — govern, the third column of the decision sequence.
 *
 * Position size is a privilege this desk earns rather than a setting, and the
 * panel says so: the tier, what it permits, and exactly what it would take to
 * size up. `next_promotion` comes from the backend as finished copy.
 *
 * Note that no colour here is `--oxide`, even when the desk has a breach on
 * record. That red is spent on failed gates and nothing else.
 */

import { dollars, pct } from "@/lib/format";
import type { RiskAuthority } from "@/lib/types";

const MAX_TIER = 2;

function TierPips({ tier }: { tier: number }) {
  return (
    <span className="inline-flex gap-1" aria-hidden>
      {Array.from({ length: MAX_TIER + 1 }, (_, i) => (
        <span
          key={i}
          className="inline-block h-2 w-2"
          style={{
            background: i <= tier ? "var(--brass)" : "transparent",
            border: `1px solid ${i <= tier ? "var(--brass)" : "var(--line)"}`,
            borderRadius: "1px",
          }}
        />
      ))}
    </span>
  );
}

function Row({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2 py-1">
      <span className="mono text-[10px] uppercase tracking-wider text-[color:var(--text-dim)]">
        {label}
      </span>
      <span className="mono text-[12px]">
        {value}
        {hint && <span className="ml-1 text-[color:var(--text-dim)]">{hint}</span>}
      </span>
    </div>
  );
}

export function RiskPanel({ risk }: { risk: RiskAuthority | undefined }) {
  if (!risk) {
    return (
      <section className="p-3" aria-label="Risk authority">
        <p className="mono mb-2 text-[10px] uppercase tracking-widest text-[color:var(--text-dim)]">
          risk authority
        </p>
        <p className="text-xs text-[color:var(--text-dim)]">
          Waiting on the backend. The tier persists in SQLite, so it survives a restart.
        </p>
      </section>
    );
  }

  const used = risk.budget_dollars > 0 ? risk.used_dollars / risk.budget_dollars : 0;

  return (
    <section className="p-3" aria-label="Risk authority">
      <p className="mono mb-2 text-[10px] uppercase tracking-widest text-[color:var(--text-dim)]">
        risk authority
      </p>

      <div className="flex items-baseline gap-2">
        <span className="font-display text-[length:var(--fs-md)]">Tier {risk.tier}</span>
        <TierPips tier={risk.tier} />
        <span className="mono ml-auto text-[11px] text-[color:var(--text-dim)]">
          {pct(risk.max_loss_pct, 1)} / trade
        </span>
      </div>

      <div className="mt-3 border-t border-[color:var(--line)] pt-2">
        <Row label="budget" value={dollars(risk.budget_dollars)} />
        <Row label="used" value={dollars(risk.used_dollars)} hint={`(${pct(used)})`} />
        <Row label="available" value={dollars(risk.available_dollars)} />
        <Row label="drawdown" value={`${risk.drawdown_pct.toFixed(2)}%`} />
      </div>

      <div className="mt-2 border-t border-[color:var(--line)] pt-2">
        <Row
          label="positions"
          value={`${risk.open_positions} / ${risk.max_concurrent_positions}`}
        />
        <Row label="closed" value={String(risk.closed_trades)} />
        <Row label="breaches" value={String(risk.breaches)} />
      </div>

      {/* Finished copy from the backend: what it takes to size up. */}
      <p className="mt-3 border-t border-[color:var(--line)] pt-2 text-[11px] leading-relaxed text-[color:var(--text-dim)]">
        {risk.next_promotion}
      </p>
    </section>
  );
}
