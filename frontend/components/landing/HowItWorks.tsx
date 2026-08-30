"use client";

/**
 * The mechanism in fifteen seconds: measure, construct, prove. Each step
 * carries a real miniature instrument — a live VRP readout, a payoff shape,
 * a compressed stress grid — never an icon.
 */

import { CountUp } from "@/components/CountUp";
import { Reveal } from "@/components/Reveal";
import { regimeColor, volPoints } from "@/lib/format";
import type { RefusalExhibit, VolState } from "@/lib/types";

/** The defined-risk payoff shape — a credit vertical. Geometry, not numbers:
 *  the point is the flat floor, loss capped by construction. */
function PayoffMini() {
  return (
    <svg viewBox="0 0 220 90" className="h-auto w-full max-w-[220px]" aria-hidden>
      <line x1="8" y1="45" x2="212" y2="45" stroke="var(--line)" />
    {/* loss floor -> slope -> profit ceiling */}
      <path
        d="M8 68 L88 68 L138 22 L212 22"
        fill="none"
        stroke="var(--brass)"
        strokeWidth="1.5"
      />
      <text x="10" y="80" className="mono" fontSize="7.5" fill="var(--text-dim)">
        max loss — computed before the position exists
      </text>
      <text x="140" y="16" className="mono" fontSize="7.5" fill="var(--text-dim)">
        max profit
      </text>
    </svg>
  );
}

/** The 84-scenario grid at glyph scale, from a REAL refusal. */
function StressMini({ exhibit }: { exhibit?: RefusalExhibit }) {
  const cells = (exhibit?.cells ?? []).filter((c) => c.time_point === "MID");
  if (cells.length === 0) return null;
  const shocks = [...new Set(cells.map((c) => c.price_shock))].sort((a, b) => a - b);
  const ivs = [...new Set(cells.map((c) => c.iv_shock))].sort((a, b) => a - b);
  return (
    <div>
      <div
        className="grid gap-[2px]"
        style={{ gridTemplateColumns: `repeat(${shocks.length}, 1fr)`, maxWidth: 220 }}
        aria-hidden
      >
        {ivs.map((iv) =>
          shocks.map((px) => {
            const cell = cells.find((c) => c.price_shock === px && c.iv_shock === iv);
            const breached = cell?.breached ?? false;
            return (
              <span
                key={`${px}-${iv}`}
                className="h-3.5"
                style={{
                  borderRadius: "1px",
                  background: breached
                    ? "color-mix(in srgb, var(--oxide) 32%, var(--panel))"
                    : (cell?.pnl ?? 0) >= 0
                      ? "color-mix(in srgb, var(--verdigris) 7%, var(--panel))"
                      : "color-mix(in srgb, var(--brass-dim) 22%, var(--panel))",
                }}
              />
            );
          }),
        )}
      </div>
      <p className="mono mt-2 text-[8px] uppercase tracking-wider text-[color:var(--text-dim)]">
        a real grid — the shaded corner is why it refused
      </p>
    </div>
  );
}

interface Props {
  states: VolState[];
  exhibit?: RefusalExhibit;
}

export function HowItWorks({ states, exhibit }: Props) {
  const widest = [...states].sort((a, b) => Math.abs(b.vrp) - Math.abs(a.vrp))[0];

  const steps = [
    {
      n: "01",
      title: "MEASURE",
      body:
        "Implied volatility against realized, across eight names. When the market " +
        "charges more for movement than movement delivers, that gap is the signal. " +
        "Direction is never an input.",
      instrument: widest ? (
        <div>
          <p className="mono text-[10px] text-[color:var(--text-dim)]">
            {widest.symbol} · widest gap now
          </p>
          <CountUp
            value={widest.vrp}
            format={(v) => volPoints(v)}
            className="font-display block text-[2.6rem] leading-tight"
            style={{ color: regimeColor(widest.regime) }}
          />
          <p className="mono text-[9px] uppercase tracking-wider text-[color:var(--text-dim)]">
            iv − rv, vol points
          </p>
        </div>
      ) : null,
    },
    {
      n: "02",
      title: "CONSTRUCT",
      body:
        "Defined-risk structures sized backwards from the risk budget. Maximum loss " +
        "is computed before the position exists.",
      instrument: <PayoffMini />,
    },
    {
      n: "03",
      title: "PROVE",
      body:
        "Every structure is repriced across 84 scenarios before execution. One breach " +
        "and it doesn't trade.",
      instrument: <StressMini exhibit={exhibit} />,
    },
  ];

  return (
    <div className="grid gap-4 md:grid-cols-3">
      {steps.map((step, i) => (
        <Reveal key={step.n} delay={i * 60}>
          <div className="panel h-full p-6" style={{ borderRadius: "3px" }}>
            <p className="mono text-[10px] text-[color:var(--text-dim)]">{step.n}</p>
            <h3 className="mono mt-1 text-[12px] uppercase tracking-[0.2em] text-[color:var(--text)]">
              {step.title}
            </h3>
            <p className="mt-3 text-[13px] leading-relaxed text-[color:var(--text-dim)]">
              {step.body}
            </p>
            <div className="mt-5">{step.instrument}</div>
          </div>
        </Reveal>
      ))}
    </div>
  );
}
