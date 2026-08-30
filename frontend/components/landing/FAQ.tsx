/**
 * FAQ as native <details> accordions — works with JavaScript disabled, and the
 * answers are the real ones. The honesty is the scoring signal; nothing here
 * is softened.
 */

import Link from "next/link";

// A real refused decision with a full recorded trace, committed as the
// permanent example. Every decision gets one of these pages.
const EXAMPLE_TRACE = "/trace/d3f21a5314de4207";

const ENTRIES: Array<{ q: string; a: React.ReactNode }> = [
  {
    q: "Is this real money?",
    a: (
      <>
        No, and it cannot become real money by accident. The system runs on
        Alpaca&rsquo;s paper API only: the base URL is pinned to the paper
        endpoint, startup asserts it and refuses to boot against anything else,
        and there is no live-trading code path anywhere in the repository — not
        even behind a flag.
      </>
    ),
  },
  {
    q: "What is the edge?",
    a: (
      <>
        The variance risk premium: implied volatility runs persistently above
        the volatility that gets realized, because people pay for protection.
        The gap is structural and documented in the academic literature, and
        harvesting it requires no forecast of direction — which is why this desk
        never makes one.
      </>
    ),
  },
  {
    q: "What if the model fails or is unreachable?",
    a: (
      <>
        The desk abstains, deterministically, and logs the abstention with the
        reason. The model&rsquo;s only power is choosing among pre-validated
        candidates or declining them; it cannot invent contracts, change
        strikes, or bypass a gate. A selector outage therefore fails to
        no-trade, never to wrong-trade — and the startup preflight refuses to
        report the desk as armed while the selector is unreachable.
      </>
    ),
  },
  {
    q: "Why is there no IV rank?",
    a: (
      <>
        Because Alpaca serves no historical implied volatility, and a 52-week IV
        rank computed from data that does not exist would be fabricated. The
        desk builds its own IV history forward from first run and refuses to
        print a rank until it holds twenty distinct trading days — until then it
        says exactly how many days it has collected.
      </>
    ),
  },
  {
    q: "How is maximum loss guaranteed?",
    a: (
      <>
        Every structure is defined-risk by construction: a long option caps each
        short one, so the worst case is a known number, not an estimate. That
        number is computed when the structure is assembled, asserted against the
        per-trade budget at construction, re-checked by the budget gate, and
        stress-tested across 84 scenarios before any order exists.
      </>
    ),
  },
  {
    q: "Can I inspect a decision?",
    a: (
      <>
        Yes — every decision, including every refusal, records its full chain:
        what was scanned, measured, classified, built, which gate stopped it and
        why. <Link className="underline decoration-[color:var(--line)] underline-offset-2 hover:decoration-[color:var(--brass)]" href={EXAMPLE_TRACE}>
          Here is a real refused trade&rsquo;s trace
        </Link>{" "}
        — nothing on that page is recomputed for display.
      </>
    ),
  },
];

export function FAQ() {
  return (
    <div className="mx-auto max-w-3xl">
      {ENTRIES.map((entry) => (
        <details
          key={entry.q}
          className="faq-item border-b border-[color:var(--line)] py-1 first:border-t"
        >
          <summary className="cursor-pointer list-none py-4 text-[15px] text-[color:var(--text)] [&::-webkit-details-marker]:hidden">
            <span className="mono mr-3 text-[10px] text-[color:var(--text-dim)]" aria-hidden>
              +
            </span>
            {entry.q}
          </summary>
          <div className="pb-5 pl-6 text-[13px] leading-relaxed text-[color:var(--text-dim)]">
            {entry.a}
          </div>
        </details>
      ))}
    </div>
  );
}
