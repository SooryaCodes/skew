"use client";

/**
 * The landing page — a product page, not an essay.
 *
 * Spine: nav → hero with the REAL product shot → built-on → the argument →
 * how it works → feature bento → the refusal (pinned) → architecture →
 * by the numbers → FAQ → final CTA → footer.
 *
 * Data comes from the three-state snapshot spine: live, last-known, or a real
 * recorded example from the audit history — labelled, never invented, never
 * empty. Live data enhances a section; it never constitutes one.
 */

import Link from "next/link";

import { Bento } from "@/components/landing/Bento";
import { BuiltOn } from "@/components/landing/BuiltOn";
import { FAQ } from "@/components/landing/FAQ";
import { Hero } from "@/components/landing/Hero";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { Nav } from "@/components/landing/Nav";
import { Numbers } from "@/components/landing/Numbers";
import { PinnedRefusal } from "@/components/landing/PinnedRefusal";
import { SmoothScroll } from "@/components/landing/SmoothScroll";
import { GateChain } from "@/components/GateChain";
import { Reveal } from "@/components/Reveal";
import { Texture } from "@/components/Texture";
import { fieldProvenance, useSnapshot } from "@/lib/snapshot";

const GITHUB = "https://github.com/USER/skew";

/** Vertical rhythm on the 96 / 144 / 192 scale — nothing in between. */
const RHYTHM = { minor: "96px", major: "144px", grand: "192px" };

function SectionCaption({ children }: { children: React.ReactNode }) {
  return (
    <Reveal>
      <p className="mono mb-10 text-[10px] uppercase tracking-widest text-[color:var(--text-dim)]">
        {children}
      </p>
    </Reveal>
  );
}

export default function Landing() {
  const { data: snapshot } = useSnapshot();
  const status = snapshot?.data.status;
  const states = snapshot?.data.universe ?? [];
  const exhibit = snapshot?.data.exhibit;
  const counts = snapshot?.data.counts;
  const latest = snapshot?.data.latest?.[0];
  const surface = snapshot?.data.surface;
  const risk = snapshot?.data.risk;
  const isLive = snapshot?.state === "live" && snapshot.field_states?.status === "live";
  const closed = status ? !status.market_open : false;

  const traced =
    counts?.TOTAL ??
    Object.entries(counts ?? {})
      .filter(([k]) => k !== "TOTAL")
      .reduce((a, [, v]) => a + (typeof v === "number" ? v : 0), 0);
  const refused = counts?.REFUSED ?? 0;
  const executed = counts?.EXECUTED ?? 0;

  return (
    <div className="relative min-h-screen">
      <SmoothScroll />
      <Texture />
      <Nav />

      {/* 2 — HERO + product shot */}
      <Hero
        status={status}
        surface={surface}
        isLive={isLive}
        recordedAt={snapshot?.recorded_at}
      />

      {/* 3 — BUILT ON */}
      <BuiltOn />

      {/* 4 — THE PROBLEM / THE APPROACH */}
      <section
        aria-label="The argument"
        className="relative z-10 mx-auto w-full max-w-5xl px-6"
        style={{ paddingBlock: RHYTHM.minor }}
      >
        <div className="grid gap-10 md:grid-cols-2">
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

      {/* 5 — HOW IT WORKS */}
      <section
        id="how-it-works"
        aria-label="How it works"
        className="relative z-10 mx-auto w-full max-w-6xl scroll-mt-20 px-6"
        style={{ paddingBlock: RHYTHM.major }}
      >
        <SectionCaption>how it works — three steps, no forecast</SectionCaption>
        <HowItWorks states={states} exhibit={exhibit} />
      </section>

      {/* 6 — FEATURE BENTO */}
      <section
        aria-label="The desk, live"
        className="relative z-10 mx-auto w-full max-w-6xl px-6"
        style={{ paddingBlock: RHYTHM.major, paddingTop: 0 }}
      >
        <SectionCaption>the instruments — every cell is the real desk</SectionCaption>
        <Bento
          states={states}
          counts={counts}
          latest={latest}
          risk={risk}
          closed={closed}
          provenance={snapshot ? fieldProvenance(snapshot, "universe") : null}
        />
      </section>

      {/* 7 — THE REFUSAL, the one pinned section */}
      <PinnedRefusal
        exhibit={exhibit}
        provenance={snapshot ? fieldProvenance(snapshot, "exhibit") : null}
      />

      {/* 8 — ARCHITECTURE */}
      <section
        id="architecture"
        aria-label="Architecture"
        className="relative z-10 mx-auto w-full max-w-5xl scroll-mt-20 px-6"
        style={{ paddingBlock: RHYTHM.major }}
      >
        <SectionCaption>deterministic gates · bounded selector</SectionCaption>
        <Reveal delay={40}>
          <GateChain />
        </Reveal>
        <Reveal delay={80}>
          <p className="mt-8 max-w-xl text-[14px] leading-relaxed text-[color:var(--text)]">
            The model can choose among approved structures. It cannot invent one.
          </p>
        </Reveal>
      </section>

      {/* 9 — BY THE NUMBERS */}
      <section
        aria-label="By the numbers"
        className="relative z-10 mx-auto w-full max-w-5xl px-6"
        style={{ paddingBlock: RHYTHM.major }}
      >
        <SectionCaption>by the numbers</SectionCaption>
        <Numbers
          traced={traced}
          tracedProvenance={snapshot ? fieldProvenance(snapshot, "counts") : null}
        />
      </section>

      {/* 10 — FAQ */}
      <section
        id="faq"
        aria-label="FAQ"
        className="relative z-10 mx-auto w-full max-w-5xl scroll-mt-20 px-6"
        style={{ paddingBlock: RHYTHM.minor }}
      >
        <SectionCaption>questions a judge should ask</SectionCaption>
        <FAQ />
      </section>

      {/* 11 — FINAL CTA */}
      <section
        aria-label="Final call to action"
        className="relative z-10 mx-auto w-full max-w-5xl px-6 text-center"
        style={{ paddingBlock: RHYTHM.grand }}
      >
        <Reveal>
          <h2 className="font-display text-[2.4rem] leading-tight sm:text-[3.4rem]">
            See what it decided today.
          </h2>
        </Reveal>
        <Reveal delay={60}>
          <div className="mt-8">
            <Link
              href="/desk"
              className="t-fast mono inline-block border border-[color:var(--brass)] bg-[color:var(--brass)] px-7 py-3 text-[12px] uppercase tracking-widest text-[color:var(--ground)] hover:bg-transparent hover:text-[color:var(--text)]"
              style={{ borderRadius: "var(--radius)" }}
            >
              Enter the desk
            </Link>
          </div>
        </Reveal>
      </section>

      {/* 12 — FOOTER */}
      <footer className="relative z-10 border-t border-[color:var(--line)]">
        <div
          className="mx-auto flex w-full max-w-6xl flex-wrap items-baseline justify-between gap-4 px-6"
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
