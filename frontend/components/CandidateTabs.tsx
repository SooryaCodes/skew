"use client";

/**
 * The candidate selector — a tab strip ABOVE the detail, not rows below it.
 *
 * The collapsed rows read as a footer list; a test user took several seconds
 * to work out they were clickable. Tabs make the affordance instant: every
 * candidate is visible at once, each carrying its verdict — the five gate
 * glyphs, with a failing gate in --oxide — so the outcome is legible without
 * clicking anything.
 *
 * Proper ARIA tabs: roving tabindex, arrow keys move and select, Home/End
 * jump. The detail panel below is the tabpanel.
 */

import { useRef } from "react";

import { dollars, structureLabel } from "@/lib/format";
import type { Candidate } from "@/lib/types";

interface Props {
  candidates: Candidate[];
  activeId: string;
  onSelect: (id: string) => void;
}

function tabId(id: string): string {
  return `cand-tab-${id.replace(/[^a-zA-Z0-9]/g, "-")}`;
}

export function panelId(id: string): string {
  return `cand-panel-${id.replace(/[^a-zA-Z0-9]/g, "-")}`;
}

export function CandidateTabs({ candidates, activeId, onSelect }: Props) {
  const listRef = useRef<HTMLDivElement | null>(null);

  const onKeyDown = (event: React.KeyboardEvent) => {
    const index = candidates.findIndex((c) => c.structure.id === activeId);
    if (index === -1) return;
    let next: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      next = (index + 1) % candidates.length;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      next = (index - 1 + candidates.length) % candidates.length;
    } else if (event.key === "Home") {
      next = 0;
    } else if (event.key === "End") {
      next = candidates.length - 1;
    }
    if (next === null) return;
    event.preventDefault();
    const chosen = candidates[next]!;
    onSelect(chosen.structure.id);
    // Selection follows focus: move focus to the newly active tab.
    listRef.current
      ?.querySelector<HTMLButtonElement>(`#${tabId(chosen.structure.id)}`)
      ?.focus();
  };

  return (
    <div
      ref={listRef}
      role="tablist"
      aria-label="Candidates"
      className="flex flex-wrap gap-x-1 border-b border-[color:var(--line)]"
      onKeyDown={onKeyDown}
    >
      {candidates.map((candidate) => {
        const s = candidate.structure;
        const active = s.id === activeId;
        const strikes = s.legs
          .map((l) => l.strike)
          .sort((a, b) => a - b)
          .join("/");

        return (
          <button
            key={s.id}
            id={tabId(s.id)}
            type="button"
            role="tab"
            aria-selected={active}
            aria-controls={panelId(s.id)}
            tabIndex={active ? 0 : -1}
            onClick={() => onSelect(s.id)}
            className="t-fast px-3 py-2 text-left"
            style={{
              borderBottom: active ? "2px solid var(--brass)" : "2px solid transparent",
              marginBottom: "-1px",
            }}
          >
            <span className="flex items-baseline gap-2">
              <span
                className="text-[12px]"
                style={{ color: active ? "var(--text)" : "var(--text-dim)" }}
              >
                {structureLabel(s.kind)}
              </span>
              <span className="mono text-[10px] text-[color:var(--text-dim)]">{strikes}</span>
            </span>
            <span className="mt-0.5 flex items-baseline gap-2">
              {/* The verdict, visible without clicking: failing gates in oxide. */}
              <span className="mono flex gap-[3px] text-[10px]" aria-hidden>
                {candidate.gates.map((gate) => (
                  <span
                    key={gate.gate}
                    title={`${gate.gate}: ${
                      gate.skipped ? "n/a" : gate.passed ? "passed" : "failed"
                    }`}
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
              <span className="mono text-[9px] text-[color:var(--text-dim)]">
                {dollars(s.max_loss, 0)}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
