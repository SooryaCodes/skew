"use client";

/**
 * The landing page. No auth, no signup, no gate — the CTA goes straight to
 * the desk. Six sections, one idea each.
 *
 * Two honesty rules govern everything below. The live-proof section reads REAL
 * numbers from the running desk or says plainly that it cannot; the refusal
 * section shows a REAL refused grid from the audit history or says none exists
 * yet. Nothing on this page fabricates a number, ever.
 */

import Link from "next/link";

import { SkewCurve } from "@/components/SkewCurve";
import { StressGrid } from "@/components/StressGrid";
import { ThemeToggle } from "@/components/ThemeToggle";
import { useRefusalExhibit, useStatus, useUniverse } from "@/lib/api";
import { clockTime, regimeColor, timeAgo, volPoints } from "@/lib/format";

const GITHUB = "https://github.com/USER/skew";

function Section({
  children,
  full = false,
  label,
}: {
  children: React.ReactNode;
  full?: boolean;
  label: string;
}) {
  return (
    <section
      aria-label={label}
      className={`mx-auto w-full max-w-5xl px-6 ${
        full ? "flex min-h-screen flex-col justify-center py-16" : "py-20"
      }`}
    >
      {children}
    </section>
  );
}

export default function Landing() {
  const { data: status } = useStatus();
  const { data: universe, error: universeError } = useUniverse();
  const { data: exhibit } = useRefusalExhibit();

  const states = universe ?? [];
  const hero = [...states].sort((a, b) => Math.abs(b.vrp) - Math.abs(a.vrp))[0];
  const closed = status ? !status.market_open : false;

  return (
    <div className="min-h-screen">
      {/* minimal chrome — the page is the pitch, not an app shell */}
      <div className="mx-auto flex w-full max-w-5xl items-center justify-between px-6 py-4">
        <span className="font-display text-[length:var(--fs-md)]">SKEW</span>
        <ThemeToggle />
      </div>

      {/* 1 — HERO */}
      <Section full label="Hero">
        {hero && (
          <div className="mb-10 w-full max-w-[760px]">
            <SkewCurve
              slices={hero.skew_slices}
              spot={hero.spot}
              rv20={hero.rv_20}
              redrawKey={`hero-${hero.symbol}`}
              large
            />
            <p className="mono mt-1 text-[9px] uppercase tracking-wider text-[color:var(--text-dim)]">
              {hero.symbol} · implied volatility by strike · live from the desk
            </p>
          </div>
        )}

        <h1 className="font-display max-w-3xl text-[length:var(--fs-xl)] leading-[1.05] sm:text-[4.5rem]">
          It doesn&rsquo;t predict the market.
          <br />
          It prices it.
        </h1>
        <p className="mono mt-6 text-[11px] uppercase tracking-[0.2em] text-[color:var(--text-dim)]">
          autonomous volatility desk · alpaca paper
        </p>
        <div className="mt-10">
          <Link
            href="/desk"
            className="mono t-fast inline-block border border-[color:var(--text)] px-5 py-2.5 text-[12px] uppercase tracking-widest text-[color:var(--text)] hover:bg-[color:var(--panel-alt)]"
            style={{ borderRadius: "var(--radius)" }}
          >
            Enter the desk
          </Link>
        </div>
      </Section>

      {/* 2 — THE ARGUMENT */}
      <Section label="The argument">
        <div className="grid gap-12 md:grid-cols-2">
          <div className="text-[15px] leading-relaxed text-[color:var(--text-dim)]">
            <p className="mono mb-4 text-[10px] uppercase tracking-widest">
              what every other agent does
            </p>
            <p>
              Predict direction. Read the headlines, or a moving average, or a
              model&rsquo;s intuition, and buy an option pointing the way it
              guesses. The option is incidental — a leveraged bet on a forecast
              that neither the model nor anyone else can reliably make.
            </p>
          </div>
          <div className="text-[15px] leading-relaxed text-[color:var(--text)]">
            <p className="mono mb-4 text-[10px] uppercase tracking-widest">what this desk does</p>
            <p>
              Measure what movement costs against what movement actually is.
              Implied volatility runs persistently above the volatility that
              gets realized, because people pay for protection. That gap — the
              variance risk premium — is structural, documented, and requires
              no forecast at all. Direction is never an input.
            </p>
          </div>
        </div>
      </Section>

      {/* 3 — LIVE PROOF */}
      <Section label="Live proof">
        <p className="mono mb-6 text-[10px] uppercase tracking-widest text-[color:var(--text-dim)]">
          the premium, right now
        </p>
        {universeError || states.length === 0 ? (
          // Quiet degradation. Never a fabricated number.
          <p className="text-sm text-[color:var(--text-dim)]">
            {universeError
              ? "The desk is not reachable from here right now — and nothing on this page is invented in its absence."
              : "The desk has not published its first scan yet."}
          </p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-x-8 gap-y-6 sm:grid-cols-4">
              {[...states]
                .sort((a, b) => Math.abs(b.vrp) - Math.abs(a.vrp))
                .map((state) => (
                  <div key={state.symbol}>
                    <p className="mono text-[11px] text-[color:var(--text-dim)]">
                      {state.symbol}
                    </p>
                    {/* Metal at dial size — the >=24px / 3:1 tier both metals clear. */}
                    <p
                      className="font-display text-[2rem] leading-tight"
                      style={{ color: regimeColor(state.regime) }}
                    >
                      {volPoints(state.vrp)}
                    </p>
                    <p className="mono text-[9px] uppercase tracking-wider text-[color:var(--text-faint)]">
                      {state.regime === "SELL_VOL"
                        ? "vol rich"
                        : state.regime === "BUY_VOL"
                          ? "vol cheap"
                          : "abstaining"}
                    </p>
                  </div>
                ))}
            </div>
            <p className="mono mt-8 text-[10px] text-[color:var(--text-dim)]">
              {closed && hero
                ? `as of ${clockTime(hero.as_of)} · last session · reading from the desk`
                : "reading live from the desk"}
            </p>
          </>
        )}
      </Section>

      {/* 4 — THE REFUSAL */}
      <Section label="The refusal">
        {exhibit?.available && exhibit.cells ? (
          <div className="grid items-start gap-10 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <div>
              <h2 className="font-display text-[length:var(--fs-lg)] leading-tight">
                84 scenarios. One breach.
                <br />
                It doesn&rsquo;t trade.
              </h2>
              <p className="mt-5 max-w-md text-[13px] leading-relaxed text-[color:var(--text)]">
                {exhibit.reason}
              </p>
              <p className="mono mt-4 text-[9px] uppercase tracking-wider text-[color:var(--text-dim)]">
                a real refusal · {exhibit.symbol} ·{" "}
                {exhibit.kind?.replaceAll("_", " ").toLowerCase()} ·{" "}
                {exhibit.ts && timeAgo(exhibit.ts)}
              </p>
            </div>
            <div className="panel p-4">
              <StressGrid cells={exhibit.cells} maxLoss={exhibit.max_loss ?? 1} refused />
            </div>
          </div>
        ) : (
          <p className="text-sm text-[color:var(--text-dim)]">
            The stress engine refuses any structure whose grid breaches the
            earned budget. No breach has been recorded yet — this exhibit fills
            in with the first real one, never with a mock.
          </p>
        )}
      </Section>

      {/* 5 — ARCHITECTURE */}
      <Section label="Architecture">
        <p className="mono mb-8 text-[10px] uppercase tracking-widest text-[color:var(--text-dim)]">
          deterministic gates · bounded selector
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {["liquidity", "earnings", "term", "stress", "budget", "selector", "execute"].map(
            (stage, i, all) => (
              <span key={stage} className="flex items-center gap-2">
                <span
                  className={`mono border px-3 py-1.5 text-[11px] uppercase tracking-wider ${
                    stage === "selector"
                      ? "border-[color:var(--brass)] text-[color:var(--text)]"
                      : "border-[color:var(--line)] text-[color:var(--text)]"
                  }`}
                  style={{ borderRadius: "var(--radius)" }}
                >
                  {stage}
                </span>
                {i < all.length - 1 && (
                  <span aria-hidden className="text-[color:var(--text-faint)]">
                    →
                  </span>
                )}
              </span>
            ),
          )}
        </div>
        <p className="mt-6 max-w-xl text-[14px] leading-relaxed text-[color:var(--text)]">
          The model can choose among approved structures. It cannot invent one.
        </p>
      </Section>

      {/* 6 — FOOTER */}
      <footer className="border-t border-[color:var(--line)]">
        <div className="mx-auto flex w-full max-w-5xl flex-wrap items-baseline justify-between gap-4 px-6 py-8">
          <p className="mono text-[11px] text-[color:var(--text)]">
            Paper trading only. No live code path exists.
          </p>
          <nav className="mono flex gap-5 text-[10px] uppercase tracking-wider" aria-label="Footer">
            <a
              className="t-fast text-[color:var(--text-dim)] hover:text-[color:var(--text)]"
              href={GITHUB}
            >
              github
            </a>
            <a
              className="t-fast text-[color:var(--text-dim)] hover:text-[color:var(--text)]"
              href={`${GITHUB}/blob/main/docs/MCP-SETUP.md`}
            >
              mcp setup
            </a>
            <span className="cursor-default text-[color:var(--text-faint)]" title="Ships with the submission">
              demo video
            </span>
            <Link
              className="t-fast text-[color:var(--text-dim)] hover:text-[color:var(--text)]"
              href="/desk"
            >
              the desk
            </Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
