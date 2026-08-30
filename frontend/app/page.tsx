"use client";

/**
 * The landing page — the pitch as a printed object.
 *
 * Hero: the volatility surface itself, drawn from the live chain, which
 * flattens into the margin as the argument scrolls over it. Film grain and a
 * faint grid stand in for depth; there are no gradients anywhere.
 *
 * Two honesty rules govern everything below. The live-proof section reads
 * REAL numbers from the running desk or says plainly that it cannot; the
 * refusal section shows a REAL refused grid from the audit history or says
 * none exists yet. Nothing on this page fabricates a number, ever.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { CountUp } from "@/components/CountUp";
import { GateChain } from "@/components/GateChain";
import { Reveal } from "@/components/Reveal";
import { Sparkline } from "@/components/Sparkline";
import { StressGrid } from "@/components/StressGrid";
import { Texture } from "@/components/Texture";
import { ThemeToggle } from "@/components/ThemeToggle";
import { VolatilitySurface } from "@/components/VolatilitySurface";
import { useAuditCounts, useRefusalExhibit, useStatus, useUniverse } from "@/lib/api";
import { clockTime, regimeColor, timeAgo, volPoints } from "@/lib/format";
import { prefersReducedMotion } from "@/lib/useInView";

const GITHUB = "https://github.com/USER/skew";

/** Vertical rhythm on the 96 / 144 / 192 scale — nothing in between. */
const RHYTHM = { minor: "96px", major: "144px", grand: "192px" };

function stateLabel(regime: string): string {
  return regime === "SELL_VOL" ? "vol rich" : regime === "BUY_VOL" ? "vol cheap" : "abstaining";
}

export default function Landing() {
  const { data: status } = useStatus();
  const { data: universe, error: universeError } = useUniverse();
  const { data: exhibit } = useRefusalExhibit();
  const { data: counts } = useAuditCounts();

  // Hero scroll progress: 0 at the top, 1 once a viewport has scrolled by.
  const [progress, setProgress] = useState(0);
  useEffect(() => {
    if (prefersReducedMotion()) return;
    let raf = 0;
    const onScroll = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        setProgress(Math.min(1, Math.max(0, window.scrollY / (window.innerHeight * 0.85))));
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => {
      window.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(raf);
    };
  }, []);

  const states = universe ?? [];
  const byGap = [...states].sort((a, b) => Math.abs(b.vrp) - Math.abs(a.vrp));
  const hero = byGap[0];
  const closed = status ? !status.market_open : false;

  const refused = counts?.REFUSED ?? 0;
  const executed = counts?.EXECUTED ?? 0;
  const traced = Object.values(counts ?? {}).reduce((a, b) => a + b, 0);

  return (
    <div className="relative min-h-screen">
      <Texture />

      {/* minimal chrome — the page is the pitch, not an app shell */}
      <div className="relative z-20 mx-auto flex w-full max-w-5xl items-center justify-between px-6 py-4">
        <span className="font-display text-[length:var(--fs-md)]">SKEW</span>
        <ThemeToggle />
      </div>

      {/* 1 — HERO: the surface, then the claim on top of it */}
      <section aria-label="Hero" className="relative z-10" style={{ height: "175vh" }}>
        <div className="sticky top-0 h-screen overflow-hidden">
          <VolatilitySurface symbol="SPY" progress={progress} />
          <div
            className="relative mx-auto flex h-full w-full max-w-5xl flex-col justify-center px-6"
            style={{
              // The type yields to the argument as the surface recedes.
              opacity: Math.max(0, 1 - progress * 1.6),
              transform: `translateY(${(-progress * 40).toFixed(1)}px)`,
            }}
          >
            <h1 className="font-display max-w-3xl text-[length:var(--fs-xl)] leading-[1.05] sm:text-[4.5rem]">
              It doesn&rsquo;t predict the market.
              <br />
              It prices it.
            </h1>
            <p className="mono mt-6 text-[11px] uppercase tracking-[0.2em] text-[color:var(--text-dim)]">
              autonomous volatility desk · alpaca paper
            </p>
            {hero && (
              <p className="mono mt-2 text-[9px] uppercase tracking-wider text-[color:var(--text-dim)]">
                behind this text: SPY implied volatility, every expiry 7–365d, live
              </p>
            )}
            <div className="mt-10">
              <Link
                href="/desk"
                className="mono t-fast inline-block border border-[color:var(--text)] px-5 py-2.5 text-[12px] uppercase tracking-widest text-[color:var(--text)] hover:bg-[color:var(--panel-alt)]"
                style={{ borderRadius: "var(--radius)" }}
              >
                Enter the desk
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* 2 — THE ARGUMENT */}
      <section
        aria-label="The argument"
        className="relative z-10 mx-auto w-full max-w-5xl px-6"
        style={{ paddingBlock: RHYTHM.major }}
      >
        <div className="grid gap-12 md:grid-cols-2">
          <div className="text-[15px] leading-relaxed text-[color:var(--text-dim)]">
            <Reveal>
              <p className="mono mb-4 text-[10px] uppercase tracking-widest">
                what every other agent does
              </p>
            </Reveal>
            <Reveal delay={40}>
              <p>
                Predict direction. Read the headlines, or a moving average, or a
                model&rsquo;s intuition, and buy an option pointing the way it
                guesses. The option is incidental — a leveraged bet on a forecast
                that neither the model nor anyone else can reliably make.
              </p>
            </Reveal>
          </div>
          <div className="text-[15px] leading-relaxed text-[color:var(--text)]">
            <Reveal delay={80}>
              <p className="mono mb-4 text-[10px] uppercase tracking-widest">
                what this desk does
              </p>
            </Reveal>
            <Reveal delay={120}>
              <p>
                Measure what movement costs against what movement actually is.
                Implied volatility runs persistently above the volatility that
                gets realized, because people pay for protection. That gap — the
                variance risk premium — is structural, documented, and requires
                no forecast at all. Direction is never an input.
              </p>
            </Reveal>
          </div>
        </div>
      </section>

      {/* 3 — LIVE PROOF: the premium, right now */}
      <section
        aria-label="Live proof"
        className="relative z-10 mx-auto w-full max-w-5xl px-6"
        style={{ paddingBlock: RHYTHM.major }}
      >
        <Reveal>
          <p className="mono mb-10 text-[10px] uppercase tracking-widest text-[color:var(--text-dim)]">
            the premium, right now
          </p>
        </Reveal>
        {universeError || states.length === 0 ? (
          // Quiet degradation. Never a fabricated number.
          <p className="text-sm text-[color:var(--text-dim)]">
            {universeError
              ? "The desk is not reachable from here right now — and nothing on this page is invented in its absence."
              : "The desk has not published its first scan yet."}
          </p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-x-10 gap-y-12 sm:grid-cols-4">
              {byGap.slice(0, 8).map((state, i) => (
                <Reveal key={state.symbol} delay={i * 40}>
                  <p className="mono text-[11px] text-[color:var(--text-dim)]">{state.symbol}</p>
                  {/* Metal at dial size — the >=24px / 3:1 tier both metals clear. */}
                  <CountUp
                    value={state.vrp}
                    format={(v) => volPoints(v)}
                    className="font-display block text-[2.4rem] leading-tight"
                    style={{ color: regimeColor(state.regime) }}
                  />
                  <p className="mono mb-2 text-[9px] uppercase tracking-wider text-[color:var(--text-dim)]">
                    {stateLabel(state.regime)}
                  </p>
                  <Sparkline slices={state.skew_slices} color={regimeColor(state.regime)} />
                </Reveal>
              ))}
            </div>
            <Reveal delay={160}>
              <p className="mono mt-12 text-[10px] text-[color:var(--text-dim)]">
                {closed && hero
                  ? `as of ${clockTime(hero.as_of)} · last session · reading from the desk`
                  : "reading live from the desk"}
              </p>
            </Reveal>
          </>
        )}
      </section>

      {/* 4 — THE REFUSAL */}
      <section
        aria-label="The refusal"
        className="relative z-10 mx-auto w-full max-w-5xl px-6"
        style={{ paddingBlock: RHYTHM.grand }}
      >
        {exhibit?.available && exhibit.cells ? (
          <div className="grid items-start gap-10 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <div>
              <Reveal>
                <h2 className="font-display text-[length:var(--fs-lg)] leading-tight">
                  84 scenarios. One breach.
                  <br />
                  It doesn&rsquo;t trade.
                </h2>
              </Reveal>
              <Reveal delay={40}>
                <p className="mt-5 max-w-md text-[13px] leading-relaxed text-[color:var(--text)]">
                  {exhibit.reason}
                </p>
              </Reveal>
              <Reveal delay={80}>
                <p className="mono mt-4 text-[9px] uppercase tracking-wider text-[color:var(--text-dim)]">
                  a real refusal · {exhibit.symbol} ·{" "}
                  {exhibit.kind?.replaceAll("_", " ").toLowerCase()} ·{" "}
                  {exhibit.ts && timeAgo(exhibit.ts)}
                </p>
              </Reveal>
            </div>
            <div className="panel p-4">
              <StressGrid
                cells={exhibit.cells}
                maxLoss={exhibit.max_loss ?? 1}
                refused
                animateOnView
              />
            </div>
          </div>
        ) : (
          <p className="text-sm text-[color:var(--text-dim)]">
            The stress engine refuses any structure whose grid breaches the
            earned budget. No breach has been recorded yet — this exhibit fills
            in with the first real one, never with a mock.
          </p>
        )}
      </section>

      {/* 5 — ARCHITECTURE */}
      <section
        aria-label="Architecture"
        className="relative z-10 mx-auto w-full max-w-5xl px-6"
        style={{ paddingBlock: RHYTHM.major, paddingBottom: RHYTHM.minor }}
      >
        <Reveal>
          <p className="mono mb-8 text-[10px] uppercase tracking-widest text-[color:var(--text-dim)]">
            deterministic gates · bounded selector
          </p>
        </Reveal>
        <Reveal delay={40}>
          <GateChain />
        </Reveal>
        <Reveal delay={80}>
          <p className="mt-8 max-w-xl text-[14px] leading-relaxed text-[color:var(--text)]">
            The model can choose among approved structures. It cannot invent one.
          </p>
        </Reveal>
      </section>

      {/* 6 — FOOTER */}
      <footer className="relative z-10 border-t border-[color:var(--line)]">
        <div
          className="mx-auto flex w-full max-w-5xl flex-wrap items-baseline justify-between gap-4 px-6"
          style={{ paddingBlock: "48px" }}
        >
          <div>
            <p className="mono text-[11px] text-[color:var(--text)]">
              Paper trading only. No live code path exists.
            </p>
            {counts && (
              <p className="mono mt-1.5 text-[10px] text-[color:var(--text-dim)]">
                {traced.toLocaleString("en-US")} decisions traced ·{" "}
                {refused.toLocaleString("en-US")} refused ·{" "}
                {executed.toLocaleString("en-US")} executed
              </p>
            )}
          </div>
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
            <span
              className="cursor-default text-[color:var(--text-faint)]"
              title="Ships with the submission"
            >
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
