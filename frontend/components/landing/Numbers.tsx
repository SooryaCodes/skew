"use client";

/**
 * BY THE NUMBERS. The first three are structural constants of the system and
 * always render; only the decision count is live, and it degrades to the
 * recorded figure with its label.
 */

import { CountUp } from "@/components/CountUp";
import { Reveal } from "@/components/Reveal";

interface Props {
  traced: number;
  tracedProvenance?: string | null;
}

export function Numbers({ traced, tracedProvenance }: Props) {
  const figures = [
    { value: 84, label: "scenarios per candidate" },
    { value: 5, label: "deterministic gates" },
    { value: 0, label: "live code paths" },
    { value: traced, label: "decisions traced", note: tracedProvenance },
  ];
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-10 md:grid-cols-4">
      {figures.map((figure, i) => (
        <Reveal key={figure.label} delay={i * 40}>
          <CountUp
            value={figure.value}
            format={(v) => Math.round(v).toLocaleString("en-US")}
            className="font-display block text-[3.4rem] leading-none"
          />
          <p className="mt-3 text-[14px] font-semibold uppercase tracking-[0.12em] text-[color:var(--text-dim)]">
            {figure.label}
          </p>
          {figure.note && (
            <p className="mono mt-1 text-[12px] text-[color:var(--text-dim)]">{figure.note}</p>
          )}
        </Reveal>
      ))}
    </div>
  );
}
