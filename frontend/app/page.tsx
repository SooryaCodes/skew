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

import { Bento } from "@/components/landing/Bento";
import { PinnedRefusal } from "@/components/landing/PinnedRefusal";
import { SmoothScroll } from "@/components/landing/SmoothScroll";
import { Reveal } from "@/components/Reveal";
import { Texture } from "@/components/Texture";
import { ThemeToggle } from "@/components/ThemeToggle";
import { VolatilitySurface } from "@/components/VolatilitySurface";
import { useAudit, useAuditCounts, useRefusalExhibit, useStatus, useUniverse } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { prefersReducedMotion } from "@/lib/useInView";

const GITHUB = "https://github.com/USER/skew";

/** Vertical rhythm on the 96 / 144 / 192 scale — nothing in between. */
const RHYTHM = { minor: "96px", major: "144px", grand: "192px" };

export default function Landing() {
  const { data: status } = useStatus();
  const { data: universe } = useUniverse();
  const { data: exhibit } = useRefusalExhibit();
  const { data: counts } = useAuditCounts();
  const { data: audit } = useAudit(1);

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
  const closed = status ? !status.market_open : false;

  const refused = counts?.REFUSED ?? 0;
  const executed = counts?.EXECUTED ?? 0;
  const traced = Object.values(counts ?? {}).reduce((a, b) => a + b, 0);

  return (
    <div className="relative min-h-screen">
      <SmoothScroll />
      <Texture />

      {/* minimal chrome — the page is the pitch, not an app shell */}
      <div className="relative z-20 mx-auto flex w-full max-w-5xl items-center justify-between px-6 py-4">
        <span className="font-display text-[length:var(--fs-md)]">SKEW</span>
        <ThemeToggle />
      </div>

      {/* 1 — HERO: type upper-left on a scrim, the surface sweeping beneath */}
      <section aria-label="Hero" className="relative z-10" style={{ height: "175vh" }}>
        <div className="sticky top-0 h-screen overflow-hidden">
          <VolatilitySurface symbol="SPY" progress={progress} />
          {/* The scrim — the ONE sanctioned gradient: --ground pooling behind
              the type so the headline sits on darkness while the curves stay
              visible at the edges. */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                "radial-gradient(ellipse 62% 55% at 30% 34%, color-mix(in srgb, var(--ground) 90%, transparent) 0%, color-mix(in srgb, var(--ground) 62%, transparent) 48%, transparent 74%)",
            }}
          />
          <div
            className="relative mx-auto flex h-full w-full max-w-5xl flex-col justify-start px-6 pt-[16vh]"
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
            <p className="mono mt-2 text-[9px] uppercase tracking-wider text-[color:var(--text-dim)]">
              beneath this text: SPY implied volatility, every expiry 7–365d, live
            </p>
            <div className="mt-10">
              {/* The only CTA on the page: solid panel, brass border, fill on
                  hover — it must never be lost in the curves again. */}
              <Link
                href="/desk"
                className="t-fast mono inline-block border border-[color:var(--brass)] bg-[color:var(--panel)] px-6 py-3 text-[12px] uppercase tracking-widest text-[color:var(--text)] hover:bg-[color:var(--brass)] hover:text-[color:var(--ground)]"
                style={{ borderRadius: "var(--radius)" }}
              >
                Enter the desk
              </Link>
            </div>
            {/* live status chip — immediate proof it is running */}
            {status && (
              <p className="mono mt-5 text-[10px] text-[color:var(--text-dim)]">
                <span
                  className="mr-1.5 inline-block h-[7px] w-[7px] align-middle"
                  style={{
                    background: status.broker_connected ? "var(--verdigris)" : "var(--line)",
                    borderRadius: "1px",
                  }}
                  aria-hidden
                />
                {status.broker_connected ? "live" : "standby"} ·{" "}
                {status.universe_size ?? status.universe.length} names scanned
                {status.last_cycle ? ` · last cycle ${timeAgo(status.last_cycle)}` : ""}
              </p>
            )}
          </div>
          {/* scroll cue, fading on first scroll */}
          <p
            aria-hidden
            className="mono absolute bottom-6 left-1/2 -translate-x-1/2 text-[10px] uppercase tracking-[0.25em] text-[color:var(--text-dim)]"
            style={{ opacity: Math.max(0, 1 - progress * 4) }}
          >
            scroll ↓
          </p>
        </div>
      </section>

      {/* 2 — THE BENTO: real instruments, live from the API */}
      <section
        aria-label="The desk, live"
        className="relative z-10 mx-auto w-full max-w-6xl px-6"
        style={{ paddingBlock: RHYTHM.major }}
      >
        <Reveal>
          <p className="mono mb-8 text-[10px] uppercase tracking-widest text-[color:var(--text-dim)]">
            the desk, live — every cell reads the real API
          </p>
        </Reveal>
        <Bento
          states={states}
          counts={counts}
          latest={audit?.[0]}
          exhibit={exhibit}
          status={status}
          closed={closed}
        />
      </section>

      {/* 3 — THE ARGUMENT */}
      <section
        aria-label="The argument"
        className="relative z-10 mx-auto w-full max-w-5xl px-6"
        style={{ paddingBlock: RHYTHM.minor }}
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

      {/* 4 — THE REFUSAL — the one pinned, scrubbed section */}
      <PinnedRefusal exhibit={exhibit} />

      {/* 5 — ARCHITECTURE lives in the bento's gate-chain cell; running the
          same animated token loop twice on one page would cheapen both. */}

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
