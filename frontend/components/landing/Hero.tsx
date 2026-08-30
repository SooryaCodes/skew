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

import { VolatilitySurface } from "@/components/VolatilitySurface";
import { timeAgo } from "@/lib/format";
import type { Surface, SystemStatus } from "@/lib/types";

interface Props {
  status?: SystemStatus;
  surface?: Surface;
  isLive: boolean;
  recordedAt?: string;
}

const SHOT_RECORDED = "Aug 30";

export function Hero({ status, surface, isLive, recordedAt }: Props) {
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
      {/* ambient surface — behind and below, never competing */}
      <div aria-hidden className="absolute inset-0 opacity-35">
        <VolatilitySurface surface={surface} progress={0} />
      </div>

      <div className="relative z-10 mx-auto grid w-full max-w-6xl items-center gap-12 px-6 pb-24 pt-16 lg:grid-cols-[45fr_55fr] lg:pt-24">
        {/* type block */}
        <div>
          <p
            className="mono inline-flex items-center gap-2 border border-[color:var(--line)] bg-[color:var(--panel)] px-3 py-1.5 text-[9px] uppercase tracking-[0.2em] text-[color:var(--text-dim)]"
            style={{ borderRadius: "999px" }}
          >
            <span
              className="inline-block h-[6px] w-[6px]"
              style={{ background: "var(--brass)", borderRadius: "1px" }}
              aria-hidden
            />
            alpaca paper · mcp · autonomous
          </p>
          <h1 className="font-display mt-6 text-[2.9rem] leading-[1.04] sm:text-[4rem] lg:text-[4.4rem]">
            It doesn&rsquo;t predict the market. It prices it.
          </h1>
          <p className="mt-6 max-w-[60ch] text-[15px] leading-relaxed text-[color:var(--text-dim)]">
            An options desk that measures what movement costs against what
            movement actually is — and refuses any trade whose stress grid
            breaches its budget.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link
              href="/desk"
              className="t-fast mono border border-[color:var(--brass)] bg-[color:var(--brass)] px-5 py-2.5 text-[11px] uppercase tracking-widest text-[color:var(--ground)] hover:bg-transparent hover:text-[color:var(--text)]"
              style={{ borderRadius: "var(--radius)" }}
            >
              Enter the desk
            </Link>
            <a
              href="#architecture"
              className="t-fast mono border border-[color:var(--line)] px-5 py-2.5 text-[11px] uppercase tracking-widest text-[color:var(--text)] hover:border-[color:var(--text)]"
              style={{ borderRadius: "var(--radius)" }}
            >
              Read the architecture
            </a>
          </div>
          {status && (
            <p className="mono mt-6 text-[10px] text-[color:var(--text-dim)]">
              <span
                className="mr-1.5 inline-block h-[7px] w-[7px] align-middle"
                style={{
                  background: showLiveDesk ? "var(--verdigris)" : "var(--line)",
                  borderRadius: "1px",
                }}
                aria-hidden
              />
              {showLiveDesk
                ? `armed · ${status.universe_size ?? status.universe.length} names${
                    status.last_cycle ? ` · last cycle ${timeAgo(status.last_cycle)}` : ""
                  }`
                : "paper account · desk idle"}
            </p>
          )}
        </div>

        {/* product shot — the real desk in a browser frame, tilted 2.5deg */}
        <figure
          className="relative"
          style={{ perspective: "1400px" }}
        >
          <div
            className="overflow-hidden border border-[color:var(--brass)]"
            style={{
              borderRadius: "4px",
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
              <span className="mono flex-1 text-center text-[9px] text-[color:var(--text-dim)]">
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
          <figcaption className="mono mt-2 text-right text-[9px] uppercase tracking-wider text-[color:var(--text-dim)]">
            {live
              ? "the desk, live right now"
              : `the desk · recorded ${recordedAt ? new Date(recordedAt).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : SHOT_RECORDED}`}
          </figcaption>
        </figure>
      </div>
    </section>
  );
}
