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
import { useStatus } from "@/lib/api";
import type { RiskAuthority } from "@/lib/types";

/** The provenance block: denominator and eligibility, never a scoreboard.
 *  Same scale as every other row; no green, no red, no rounding. */
function AccountStrip() {
  const { data: status } = useStatus();
  if (!status) return null;
  const suffix = status.account_id_suffix;
  const equity = status.equity;
  const starting = status.starting_equity;
  const level = status.options_approval_level;
  const money = (v: number) =>
    `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return (
    <div className="mb-3 border-b border-[color:var(--line)] pb-3">
      <Row
        label="account"
        value={suffix ? `PA••••${suffix}` : "unavailable"}
        hint={suffix ? "paper" : undefined}
      />
      <Row
        label="equity"
        value={equity != null ? money(equity) : "unavailable"}
        hint={starting != null ? `started ${money(starting)}` : undefined}
      />
      <Row
        label="options level"
        value={level != null ? String(level) : "unavailable"}
        hint={level != null ? "spreads, multi-leg" : undefined}
      />
      <Row label="endpoint" value="PAPER" hint="no live path exists" />
    </div>
  );
}

const MAX_TIER = 2;

export function TierPips({ tier }: { tier: number }) {
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
      <span className="mono text-[12px] uppercase tracking-wider text-[color:var(--text-dim)]">
        {label}
      </span>
      <span className="mono text-[14px]">
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
        <p className="mono mb-2 text-[12px] uppercase tracking-widest text-[color:var(--text-dim)]">
          risk authority
        </p>
        <p className="text-xs text-[color:var(--text-dim)]">
          Waiting on the backend. The tier persists in SQLite, so it survives a restart.
        </p>
      </section>
    );
  }

  const deployed =
    risk.portfolio_cap_dollars > 0 ? risk.used_dollars / risk.portfolio_cap_dollars : 0;

  return (
    <section className="p-3" aria-label="Risk authority">
      <p className="mono mb-2 text-[12px] uppercase tracking-widest text-[color:var(--text-dim)]">
        risk authority
      </p>

      <AccountStrip />

      <div className="flex items-baseline gap-2">
        <span className="font-display text-[length:var(--fs-md)]">Tier {risk.tier}</span>
        <TierPips tier={risk.tier} />
        <span className="mono ml-auto text-[13px] text-[color:var(--text-dim)]">
          {pct(risk.max_loss_pct, 1)} / trade
        </span>
      </div>
      {/* What promotion takes, where the tier lives — not only on /positions. */}
      {risk.next_promotion && (
        <p className="mt-1 text-[12px] leading-snug text-[color:var(--text-dim)]">
          {risk.next_promotion}
        </p>
      )}

      <div className="mt-3 border-t border-[color:var(--line)] pt-2">
        {/* Two separate risk dimensions. Merging them once locked the desk out. */}
        <Row label="per trade" value={dollars(risk.budget_dollars)} />
        <Row
          label="portfolio"
          value={`${dollars(risk.used_dollars)} / ${dollars(risk.portfolio_cap_dollars)}`}
          hint={`(${pct(deployed)})`}
        />
        <Row label="headroom" value={dollars(risk.available_dollars)} />
        <Row label="drawdown" value={`${(risk.drawdown_pct * 100).toFixed(2)}%`} />
      </div>

      <div className="mt-2 border-t border-[color:var(--line)] pt-2">
        <Row
          label="positions"
          value={`${risk.open_positions} / ${risk.max_concurrent_positions}`}
        />
        <Row label="closed" value={String(risk.closed_trades)} />
        <Row label="breaches" value={String(risk.breaches)} />
      </div>

      <p className="mt-3 border-t border-[color:var(--line)] pt-2 text-[13px] leading-relaxed text-[color:var(--text-dim)]">
        Tier limits are a percentage of equity. Tier 0 is 0.5% per position,
        1.5% deployed.
      </p>
      {/* Finished copy from the backend: what it takes to size up. */}
      <p className="mt-1.5 text-[13px] leading-relaxed text-[color:var(--text-dim)]">
        {risk.next_promotion}
      </p>
    </section>
  );
}
