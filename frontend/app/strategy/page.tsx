"use client";

/**
 * The strategy, as it actually runs.
 *
 * Every value on this page is read live from the desk's configuration or
 * tallied from the audit record. Nothing is hardcoded: a page showing the
 * desk's actual current parameters is evidence; a page describing them from
 * memory is marketing.
 */

import { Header } from "@/components/Header";
import { TierPips } from "@/components/RiskPanel";
import { useRisk, useStatus, useStrategy } from "@/lib/api";
import { pct } from "@/lib/format";

/** One parameter: mono value, plain-English line. The risk panel's row
 *  idiom, given room for a sentence. */
function Param({ label, value, children }: { label: string; value: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="border-t border-[color:var(--line)] py-2.5 first:border-t-0">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <span className="mono w-44 shrink-0 text-[12px] uppercase tracking-wider text-[color:var(--text-dim)]">
          {label}
        </span>
        <span className="mono text-[14px] tabular-nums text-[color:var(--text)]">{value}</span>
      </div>
      <p className="mt-1 text-[13px] leading-relaxed text-[color:var(--text-dim)] sm:pl-[11.75rem]">
        {children}
      </p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-8" aria-label={title}>
      <h2 className="mono mb-3 text-[12px] uppercase tracking-widest text-[color:var(--text-dim)]">
        {title}
      </h2>
      <div className="panel px-4 py-2">{children}</div>
    </section>
  );
}

const GATE_COPY: Record<string, { blocks: string; why: string }> = {
  liquidity: {
    blocks: "Illiquid contracts — thin open interest or wide bid-ask spreads.",
    why: "A defined-risk structure that cannot be exited at a fair price is not defined risk in practice. Floors scale with tenor: short-dated chains carry structurally less open interest.",
  },
  earnings: {
    blocks: "Short premium through an earnings report, or through an unknown report date.",
    why: "An earnings gap is exactly the move the stress grid cannot price from history. No confirmed date counts as blocked, not as clear.",
  },
  term: {
    blocks: "Premium selling into a materially inverted term structure.",
    why: "Backwardation means the market is pricing near-term stress. The gate compares the trade tenor against a 60–90 day reference and blocks only a material inversion — routine front-of-curve noise passes.",
  },
  stress: {
    blocks: "Structures whose loss path is too easy, whatever their maximum.",
    why: "Every candidate is repriced across 84 scenarios — price shocks to ±3σ, implied volatility up to doubling, at three points in time. A routine move consuming too much of the maximum loss refuses the trade even though the maximum fits the budget.",
  },
  budget: {
    blocks: "Positions that do not fit the earned limits.",
    why: "Three separate checks, each named when it refuses: the per-trade cap, the portfolio cap (committed plus resting risk), and the concurrent-position count.",
  },
};

export default function StrategyPage() {
  const { data: status } = useStatus();
  const { data: strategy } = useStrategy();
  const { data: risk } = useRisk();

  return (
    <div className="flex min-h-screen flex-col">
      <Header status={status} tab="strategy" />

      <main className="mx-auto w-full max-w-4xl flex-1 p-4 pb-12">
        <h1 className="font-display text-[length:var(--fs-md)]">Strategy</h1>
        <p className="mt-2 max-w-3xl text-[15px] leading-relaxed text-[color:var(--text)]">
          The desk never predicts price direction. It measures the spread between
          implied and realized volatility — the variance risk premium — and takes
          defined-risk options structures when volatility is priced rich or cheap.
          Deterministic code decides what is possible; a bounded model may only
          pick among pre-validated candidates or abstain; and position size is
          earned through a clean record, never assumed.
        </p>
        <p className="mono mt-2 text-[13px] text-[color:var(--text-dim)]">
          These are the parameters the desk is running right now, read from its
          configuration.
        </p>

        {!strategy ? (
          <p className="mt-6 text-sm text-[color:var(--text-dim)]">
            Reading the live configuration…
          </p>
        ) : (
          <>
            <Section title="the signal">
              <Param label="vrp entry floor" value={`+${strategy.signal.vrp_sell_floor.toFixed(1)} vol pts`}>
                Implied volatility must exceed realized by at least this much
                before the desk will consider selling premium. Below it, the
                premium is not rich — it is fairly priced.
              </Param>
              <Param label="vrp lower ceiling" value={`${strategy.signal.vrp_buy_ceiling.toFixed(1)} vol pts`}>
                Implied this far BELOW realized flips the desk to buying premium:
                movement is being sold for less than it is occurring.
              </Param>
              <Param label="realized vol" value="20d close-to-close · Parkinson check">
                Realized volatility is measured over a 20-day window, annualised,
                with a Parkinson high-low estimator alongside as a sanity check —
                both from the desk&rsquo;s own bar history.
              </Param>
              <Param label="term reference" value={`~${strategy.signal.term_far_target_dte}d tenor`}>
                The term-structure slope compares the trade tenor against this
                farther reference point, so the desk measures the curve rather
                than front-month noise.
              </Param>
              <Param
                label="backwardation floor"
                value={`${(strategy.signal.term_backwardation_floor * 100).toFixed(1)} vol pts`}
              >
                Only an inversion deeper than this blocks premium selling. The
                front of the curve inverts routinely for idiosyncratic reasons; a
                shallow dip is noise, not stress.
              </Param>
              <Param label="universe" value={strategy.signal.universe.join(" · ")}>
                Eight liquid names with active options chains, scanned every
                cycle. Liquidity is a precondition of the strategy, not a
                preference.
              </Param>
            </Section>

            <Section title="structure construction">
              <Param
                label="short-leg delta"
                value={`~${strategy.construction.short_leg_delta_target.toFixed(2)}Δ`}
              >
                Short strikes are placed by delta target, so distance from the
                money adapts to each name&rsquo;s own volatility instead of using
                a fixed percentage.
              </Param>
              <Param
                label="dte window"
                value={`${strategy.construction.target_dte_min}–${strategy.construction.target_dte_max} days`}
              >
                Entries land in this expiry window: long enough to avoid the
                worst expiry gamma, short enough that a position can realistically
                reach its profit target and close within days.
              </Param>
              <Param
                label="structures"
                value={strategy.construction.structures
                  .map((k) => k.split("_").map((w) => w[0] + w.slice(1).toLowerCase()).join(" "))
                  .join(" · ")}
              >
                Every structure is defined-risk by construction — a long option
                caps each short one — and is submitted as a single atomic
                multi-leg order, never legged in.
              </Param>
              <Param label="width selection" value="sized backwards from the budget">
                Spread widths are chosen from the per-trade budget, not the other
                way round: the desk never proposes a structure it is not
                permitted to take.
              </Param>
            </Section>

            <Section title="the gate chain">
              <p className="border-t-0 pt-2 pb-1 text-[13px] leading-relaxed text-[color:var(--text-dim)]">
                Five deterministic gates run on every candidate, in order, before
                the model is asked anything. Every result — pass or fail — is in
                the audit record; the counts below are tallied from it.
              </p>
              {strategy.gates.order.map((gate, i) => {
                const tally = strategy.gates.tallies[gate];
                const copy = GATE_COPY[gate];
                return (
                  <Param
                    key={gate}
                    label={`${i + 1} · ${gate}`}
                    value={
                      tally ? (
                        <>
                          <span style={{ color: "var(--verdigris)" }}>{tally.passed.toLocaleString()} passed</span>
                          <span className="text-[color:var(--text-dim)]"> · </span>
                          <span style={{ color: "var(--negative)" }}>{tally.refused.toLocaleString()} refused</span>
                        </>
                      ) : (
                        "no candidates evaluated yet"
                      )
                    }
                  >
                    <strong className="font-semibold text-[color:var(--text)]">
                      Blocks:
                    </strong>{" "}
                    {copy?.blocks} {copy?.why}
                  </Param>
                );
              })}
            </Section>

            <Section title="the model's role">
              <Param label="selector" value={strategy.model.name}>
                The model receives only candidates that already cleared every
                gate. It may return one identifier or an abstention — nothing
                else. No tools, no credentials, no account access, no execution
                function. Malformed output is treated as abstention and logged.
                It can choose among approved structures; it cannot invent one.
              </Param>
            </Section>

            <Section title="exits and authority">
              <Param label="profit target" value={pct(strategy.exits.profit_target_pct)}>
                Of the credit received (or maximum profit on debit structures).
                Set for a days-long horizon — on a normal horizon this would sit
                near 45%.
              </Param>
              <Param label="loss limit" value={`${strategy.exits.loss_limit_multiple}× credit`}>
                A deliberately wide stop against a modest target: the win rate
                carries the expectancy, and the structural maximum loss already
                floors the downside just past it.
              </Param>
              <Param label="dte close" value={`≤ ${strategy.exits.exit_dte_threshold} days`}>
                Every position is closed before its final days. Gamma rises
                sharply into expiry, and a quiet spread can travel its whole
                width in a day.
              </Param>
              <Param label="short-itm defence" value="always on">
                A short leg trading in the money closes the whole structure
                early. Assignment risk is not a risk this desk carries.
              </Param>
              <Param label="drawdown breaker" value={pct(strategy.exits.drawdown_breaker_pct)}>
                Past this account drawdown the desk stops opening positions until
                equity recovers. Monitoring never stops. An agent that stands
                itself down is the thesis, not a failure mode.
              </Param>

              {/* the tier ladder, with the live position on it */}
              <div className="border-t border-[color:var(--line)] py-3">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="mono w-44 shrink-0 text-[12px] uppercase tracking-wider text-[color:var(--text-dim)]">
                    risk authority
                  </span>
                  {risk && (
                    <span className="flex items-center gap-2">
                      <span className="font-display text-[15px]">Tier {risk.tier}</span>
                      <TierPips tier={risk.tier} />
                      <span className="mono text-[13px] text-[color:var(--text-dim)]">
                        {risk.closed_trades} clean close{risk.closed_trades === 1 ? "" : "s"} credited
                      </span>
                    </span>
                  )}
                </div>
                <div className="mt-2 sm:pl-[11.75rem]">
                  {strategy.tiers.map((tier) => (
                    <p
                      key={tier.level}
                      className="mono py-0.5 text-[13px]"
                      style={{
                        color:
                          risk && tier.level === risk.tier
                            ? "var(--text)"
                            : "var(--text-dim)",
                      }}
                    >
                      tier {tier.level} · {pct(tier.max_loss_pct, 1)} per trade ·{" "}
                      {pct(tier.portfolio_pct, 1)} deployed —{" "}
                      {tier.description.toLowerCase()}
                    </p>
                  ))}
                  {risk && (
                    <p className="mt-1 text-[13px] leading-relaxed text-[color:var(--text-dim)]">
                      {risk.next_promotion}
                    </p>
                  )}
                </div>
              </div>
            </Section>

            <Section title="what this desk will not do">
              <ul className="space-y-1.5 py-2">
                {[
                  "Forecast price direction. Direction is never an input.",
                  "Hold a naked short option. Every short leg is capped by a long one, by construction.",
                  "Trade live. The paper endpoint is asserted at startup; no live code path exists.",
                  "Print an IV rank it cannot compute. Alpaca serves no historical IV, so the desk builds its own history forward and says how many days it holds.",
                ].map((line) => (
                  <li key={line} className="flex gap-2.5 text-[14px] leading-relaxed text-[color:var(--text)]">
                    <span className="mono shrink-0 text-[color:var(--negative)]" aria-hidden>
                      ✗
                    </span>
                    {line}
                  </li>
                ))}
              </ul>
            </Section>
          </>
        )}
      </main>
    </div>
  );
}
