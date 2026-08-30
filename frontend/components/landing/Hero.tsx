"use client";

/**
 * The hero: type left, PRODUCT SHOT right. Not type floating on a graphic —
 * the composition every SaaS template fakes with an invented dashboard, we do
 * with the real one. Live iframe of /desk when the backend is armed; otherwise
 * the committed screenshot of the real desk, labelled with when it was
 * recorded. The skew surface renders behind at low opacity — ambient texture,
 * never a competing element. The hero is never empty.
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import type { Surface, SystemStatus } from "@/lib/types";

interface Props {
  status?: SystemStatus;
  /** Unused since the reset — the hero is type + product shot, nothing behind. */
  surface?: Surface;
  isLive: boolean;
  recordedAt?: string;
}

const SHOT_RECORDED = "Aug 30";

export function Hero({ status, isLive, recordedAt }: Props) {
  // The live desk only earns the frame when it would actually show data.
  const showLiveDesk = isLive && Boolean(status?.broker_connected);
  const [iframeDead, setIframeDead] = useState(false);
  const live = showLiveDesk && !iframeDead;

  // Scale the 1440px-wide live desk to whatever width the frame actually has.
  const frameRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = frameRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      el.style.setProperty("--shot-scale", String(el.clientWidth / 1440));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [live]);

  return (
    <section aria-label="Hero" className="relative overflow-hidden pt-16">
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
              className="t-fast bg-[color:var(--accent)] px-6 py-3.5 text-[15px] font-semibold text-white hover:opacity-90"
              style={{ borderRadius: "var(--radius)" }}
            >
              Enter the desk
            </Link>
            <a
              href="#architecture"
              className="t-fast border border-[color:var(--line)] px-6 py-3.5 text-[15px] font-semibold text-[color:var(--text)] hover:bg-[color:var(--panel-alt)]"
              style={{ borderRadius: "var(--radius)" }}
            >
              Read the architecture
            </a>
          </div>
        </div>

        {/* product shot — the real desk in a browser frame, tilted 2.5deg */}
        <figure
          className="relative"
          style={{ perspective: "1400px" }}
        >
          <div
            className="overflow-hidden border border-[color:var(--line)]"
            style={{
              borderRadius: "14px",
              transform: "rotateY(-2.5deg) rotateX(1deg)",
              transformOrigin: "center",
              background: "var(--panel)",
            }}
          >
            {/* browser chrome */}
            <div className="flex items-center gap-2 border-b border-[color:var(--line)] bg-[color:var(--panel)] px-3 py-2">
              <span className="flex gap-1.5" aria-hidden>
                {[0, 1, 2].map((i) => (
                  <span
                    key={i}
                    className="inline-block h-[8px] w-[8px] rounded-full border border-[color:var(--line)]"
                  />
                ))}
              </span>
              <span className="mono flex-1 text-center text-[12px] text-[color:var(--text-dim)]">
                skew — the desk
              </span>
            </div>
            {live ? (
              // The real thing, live, scaled into the frame. pointer-events off:
              // it is a product shot, not an embedded app.
              <div ref={frameRef} className="pointer-events-none relative aspect-[1440/860] overflow-hidden">
                <iframe
                  src="/desk"
                  title="The live desk"
                  className="absolute left-0 top-0 origin-top-left"
                  style={{ width: 1440, height: 860, transform: "scale(var(--shot-scale, 0.42))" }}
                  onError={() => setIframeDead(true)}
                  tabIndex={-1}
                  aria-hidden
                />
              </div>
            ) : (
              /* eslint-disable-next-line @next/next/no-img-element -- static shot, exact pixels */
              <img
                src="/shots/desk-recorded.png"
                alt="The SKEW desk: universe rail, volatility instruments, risk authority and the audit stream"
                className="block w-full"
                width={1440}
                height={900}
              />
            )}
          </div>
          <figcaption className="mt-3 text-right text-[13px] text-[color:var(--text-dim)]">
            {live
              ? "The desk — live right now"
              : `The desk — recorded ${recordedAt ? new Date(recordedAt).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : SHOT_RECORDED}`}
          </figcaption>
        </figure>
      </div>
    </section>
  );
}
