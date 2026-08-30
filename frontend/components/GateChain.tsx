"use client";

/**
 * The architecture, animated: a token — one trade idea — travels the gate
 * chain. Every third pass it stops at the stress gate, which flashes --oxide;
 * the gates beyond it dim, because the idea never reached them. The loop is
 * the pitch: most cycles end at a gate, and that is the product working.
 *
 * Reduced motion: a static chain with the stress gate outlined in oxide and
 * the caption shown — same information, no loop.
 */

import { useEffect, useRef, useState } from "react";

import { prefersReducedMotion } from "@/lib/useInView";

const STAGES = ["liquidity", "earnings", "term", "stress", "budget", "selector", "execute"];
const STOP_AT = 3; // stress
const HOP_MS = 520;
const HOLD_MS = 2000;

export function GateChain() {
  const [pos, setPos] = useState(0);
  const [pass, setPass] = useState(0);
  const [stopped, setStopped] = useState(false);
  const [reduced, setReduced] = useState(false);
  const gateRefs = useRef<Array<HTMLSpanElement | null>>([]);
  const [tokenX, setTokenX] = useState<number | null>(null);

  useEffect(() => {
    setReduced(prefersReducedMotion());
  }, []);

  // The timeline: advance, and on every third pass halt at the stress gate.
  useEffect(() => {
    if (reduced) return;
    const stoppingPass = pass % 3 === 2;
    let timer: ReturnType<typeof setTimeout>;
    if (stopped) {
      timer = setTimeout(() => {
        setStopped(false);
        setPos(0);
        setPass((p) => p + 1);
      }, HOLD_MS);
    } else if (stoppingPass && pos === STOP_AT) {
      timer = setTimeout(() => setStopped(true), 200);
    } else if (pos >= STAGES.length - 1) {
      timer = setTimeout(() => {
        setPos(0);
        setPass((p) => p + 1);
      }, HOLD_MS / 2);
    } else {
      timer = setTimeout(() => setPos((p) => p + 1), HOP_MS);
    }
    return () => clearTimeout(timer);
  }, [pos, pass, stopped, reduced]);

  // Token position follows the current gate's real layout box.
  useEffect(() => {
    const el = gateRefs.current[pos];
    if (el) setTokenX(el.offsetLeft + el.offsetWidth / 2 - 4);
  }, [pos, reduced]);

  const flashing = stopped;

  return (
    <div>
      <div className="relative">
        {!reduced && tokenX !== null && (
          <span
            aria-hidden
            className="absolute -top-4 h-2 w-2"
            style={{
              left: tokenX,
              background: flashing ? "var(--oxide)" : "var(--brass)",
              borderRadius: "1px",
              transition: `left ${HOP_MS - 120}ms ease, background 200ms ease`,
            }}
          />
        )}
        <div className="flex flex-wrap items-center gap-2">
          {STAGES.map((stage, i) => {
            const isStop = i === STOP_AT && (flashing || reduced);
            const beyond = flashing && i > STOP_AT;
            return (
              <span key={stage} className="flex items-center gap-2">
                <span
                  ref={(el) => {
                    gateRefs.current[i] = el;
                  }}
                  className="mono border px-3 py-1.5 text-[11px] uppercase tracking-wider"
                  style={{
                    borderRadius: "var(--radius)",
                    borderColor: isStop
                      ? "var(--oxide)"
                      : !reduced && i === pos && !flashing
                        ? "var(--brass)"
                        : "var(--line)",
                    color: "var(--text)",
                    opacity: beyond ? 0.45 : 1,
                    transition: "border-color 200ms ease, opacity 300ms ease",
                  }}
                >
                  {stage}
                </span>
                {i < STAGES.length - 1 && (
                  <span aria-hidden className="text-[color:var(--text-faint)]">
                    →
                  </span>
                )}
              </span>
            );
          })}
        </div>
      </div>
      <p
        className="mono mt-4 text-[10px] uppercase tracking-wider"
        style={{
          color: flashing || reduced ? "var(--text)" : "var(--text-dim)",
          transition: "color 300ms ease",
        }}
      >
        <span
          className="mr-1.5 inline-block h-[7px] w-[7px] align-middle"
          style={{ background: "var(--oxide)", borderRadius: "1px" }}
          aria-hidden
        />
        Most cycles end here.
      </p>
    </div>
  );
}
