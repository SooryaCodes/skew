"use client";

/**
 * THE REFUSAL — the strongest section, now pinned and scrubbed.
 *
 * The section pins for one extra viewport of scroll while the grid fills cell
 * by cell, left to right; the breach contour and worst-cell ring arrive with
 * their cells (they sit at the far edge of the fill order), and the caption
 * resolves last. The ONE pinned section on the page.
 *
 * Reduced motion or no JS: nothing pins, nothing scrubs, everything is simply
 * there — GSAP owns the hidden states, so without it the section is static and
 * complete.
 */

import { useEffect, useRef } from "react";

import { StressGrid } from "@/components/StressGrid";
import { timeAgo } from "@/lib/format";
import type { RefusalExhibit } from "@/lib/types";

interface Props {
  exhibit?: RefusalExhibit;
}

export function PinnedRefusal({ exhibit }: Props) {
  const sectionRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const section = sectionRef.current;
    if (!section || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (!exhibit?.available) return;
    let killed = false;
    let teardown: (() => void) | undefined;
    void (async () => {
      const [{ gsap }, { ScrollTrigger }] = await Promise.all([
        import("gsap"),
        import("gsap/ScrollTrigger"),
      ]);
      if (killed) return;
      gsap.registerPlugin(ScrollTrigger);
      const cells = section.querySelectorAll(".cell-anim");
      const caption = section.querySelectorAll(".refusal-caption");
      if (cells.length === 0) return;
      const timeline = gsap.timeline({
        scrollTrigger: {
          trigger: section,
          start: "top top",
          end: "+=110%",
          pin: true,
          scrub: 0.4,
        },
      });
      timeline
        .fromTo(caption, { opacity: 0.12 }, { opacity: 1, duration: 0.35 }, 0.55)
        .fromTo(
          cells,
          { opacity: 0 },
          { opacity: 1, stagger: { each: 0.012 }, duration: 0.08 },
          0,
        );
      teardown = () => {
        timeline.scrollTrigger?.kill();
        timeline.kill();
      };
    })();
    return () => {
      killed = true;
      teardown?.();
    };
  }, [exhibit?.available]);

  return (
    <section
      ref={sectionRef}
      aria-label="The refusal"
      className="relative z-10 mx-auto flex w-full max-w-5xl flex-col justify-center px-6"
      style={{ minHeight: exhibit?.available ? "100vh" : undefined, paddingBlock: "96px" }}
    >
      {exhibit?.available && exhibit.cells ? (
        <div className="grid items-center gap-10 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="refusal-caption">
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
          The stress engine refuses any structure whose grid breaches the earned
          budget. No breach has been recorded yet — this exhibit fills in with
          the first real one, never with a mock.
        </p>
      )}
    </section>
  );
}
