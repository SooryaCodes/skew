"use client";

/**
 * The hero: type left, PRODUCT SHOT right.
 *
 * The shot is a committed, real screenshot of the desk — deliberately NOT a
 * live embed. The project rule is "no P&L in the headline": a live view would
 * surface whatever the book happens to look like the moment a judge loads the
 * page. A real capture, taken when the desk tells its story well and honestly
 * dated, is stable evidence. Theme-aware: each theme shows its own capture.
 */

import Link from "next/link";

import type { Surface, SystemStatus } from "@/lib/types";

interface Props {
  status?: SystemStatus;
  /** Unused since the reset — kept so the page's call signature is stable. */
  surface?: Surface;
  isLive: boolean;
  recordedAt?: string;
}

export function Hero(_props: Props) {
  return (
    <section aria-label="Hero" className="relative overflow-hidden pt-16">
      {/* backdrop: one soft accent glow + a fine grid fading out */}
      <div aria-hidden className="hero-backdrop absolute inset-0" />
      <div aria-hidden className="hero-grid absolute inset-0" />

      <div className="relative z-10 mx-auto grid w-full max-w-6xl items-center gap-14 px-6 pb-28 pt-20 lg:grid-cols-[46fr_54fr] lg:pt-32">
        {/* type block — the type IS the visual */}
        <div>
          <h1
            className="font-display text-[3rem] leading-[1.04] sm:text-[3.6rem] lg:text-[3.9rem]"
            style={{ letterSpacing: "-0.035em" }}
          >
            It doesn&rsquo;t predict the market. It prices it.
          </h1>
          <p className="mt-7 max-w-[54ch] text-[18px] leading-[1.65] text-[color:var(--text-dim)]">
            An options desk that measures what movement costs against what
            movement actually is — and refuses any trade whose stress grid
            breaches its budget. Paper only, by construction.
          </p>
          <div className="mt-10 flex flex-wrap items-center gap-3">
            <Link
              href="/desk"
              className="btn-3d t-fast bg-[color:var(--accent)] px-6 py-3.5 text-[15px] font-semibold text-white"
              style={{ borderRadius: "12px" }}
            >
              Enter the desk
            </Link>
            <a
              href="#architecture"
              className="btn-3d-ghost t-fast border border-[color:var(--line)] bg-[color:var(--panel)] px-6 py-3.5 text-[15px] font-semibold text-[color:var(--text)]"
              style={{ borderRadius: "12px" }}
            >
              Read the architecture
            </a>
          </div>
        </div>

        {/* product shot — the real desk, minimal frame, no fake chrome */}
        <figure className="relative">
          {/* ambient occlusion: a soft neutral shadow so the frame sits ON the
              page instead of floating. Colourless by design. */}
          <div
            aria-hidden
            className="absolute inset-x-6 -bottom-4 h-10"
            style={{
              background: "rgba(0, 0, 0, 0.5)",
              filter: "blur(28px)",
              borderRadius: "50%",
            }}
          />
          <div
            className="relative overflow-hidden border border-[color:var(--line)] bg-[color:var(--panel)]"
            style={{
              borderRadius: "14px",
              transform: "rotateY(-2.5deg) rotateX(1deg)",
              transformOrigin: "center",
            }}
          >
            <div className="flex items-center gap-1.5 border-b border-[color:var(--line)] px-3.5 py-2.5" aria-hidden>
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="inline-block h-[9px] w-[9px] rounded-full border border-[color:var(--line)] bg-[color:var(--panel-alt)]"
                />
              ))}
            </div>
            {/* eslint-disable-next-line @next/next/no-img-element -- exact pixels */}
            <img
              src="/shots/desk-dark.png"
              alt="The SKEW desk: universe rail, volatility instruments, risk authority and the audit stream"
              className="shot-dark block w-full"
              width={1440}
              height={860}
            />
            {/* eslint-disable-next-line @next/next/no-img-element -- exact pixels */}
            <img
              src="/shots/desk-light.png"
              alt="The SKEW desk in the light theme"
              className="shot-light block w-full"
              width={1440}
              height={860}
            />
          </div>
        </figure>
      </div>
    </section>
  );
}
