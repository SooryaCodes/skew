"use client";

/**
 * A candidate collapsed to one line: kind · strikes · max loss · gate glyphs.
 *
 * One candidate holds the centre of the desk at full depth; the rest wait
 * here. Clicking promotes a line to focus and demotes the current card —
 * everything is still computed, just not all displayed at once.
 */

import { dollars, structureLabel } from "@/lib/format";
import type { Candidate } from "@/lib/types";

interface Props {
  candidate: Candidate;
  onFocus: (id: string) => void;
}

export function CandidateLine({ candidate, onFocus }: Props) {
  const s = candidate.structure;
  const strikes = s.legs
    .map((l) => l.strike)
    .sort((a, b) => a - b)
    .join("/");

  return (
    <button
      type="button"
      onClick={() => onFocus(s.id)}
      className="t-fast flex w-full items-baseline gap-3 border-t border-[color:var(--line)] px-1 py-1.5 text-left first:border-t-0 hover:bg-[color:var(--panel)]"
      aria-label={`Focus ${structureLabel(s.kind)} ${strikes}`}
    >
      <span className="w-28 shrink-0 text-[12px] text-[color:var(--text)]">
        {structureLabel(s.kind)}
      </span>
      <span className="mono shrink-0 text-[11px] text-[color:var(--text-dim)]">{strikes}</span>
      <span className="mono ml-auto shrink-0 text-[11px] text-[color:var(--text-dim)]">
        max loss <span className="text-[color:var(--text)]">{dollars(s.max_loss, 0)}</span>
      </span>
      <span className="mono flex shrink-0 gap-1" aria-hidden>
        {candidate.gates.map((gate) => (
          <span
            key={gate.gate}
            title={`${gate.gate}: ${gate.skipped ? "n/a" : gate.passed ? "passed" : "failed"}`}
            style={{
              color: gate.skipped
                ? "var(--text-faint)"
                : gate.passed
                  ? "var(--verdigris)"
                  : "var(--oxide)",
            }}
          >
            {gate.skipped ? "—" : gate.passed ? "✓" : "✗"}
          </span>
        ))}
      </span>
    </button>
  );
}
