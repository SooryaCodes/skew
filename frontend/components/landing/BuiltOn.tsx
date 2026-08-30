/**
 * BUILT ON — the honest version of a logo cloud. We have no customers, so a
 * "trusted by" row would be a lie; the technology row is true and tells the
 * judges exactly which sponsor surfaces this uses.
 */

const STACK = [
  "Alpaca Trading API",
  "Alpaca Options Data",
  "Model Context Protocol",
  "Claude",
  "Python",
  "Next.js",
];

export function BuiltOn() {
  return (
    <section aria-label="Built on" className="relative z-10 border-y border-[color:var(--line)]">
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-center px-6 py-7">
        <span className="mr-8 text-[13px] font-semibold uppercase tracking-[0.14em] text-[color:var(--text-faint)]">
          Built on
        </span>
        {STACK.map((name, i) => (
          <span key={name} className="mono flex items-center text-[14px] text-[color:var(--text-dim)]">
            {i > 0 && (
              <span aria-hidden className="mx-4 h-3 w-px bg-[color:var(--line)]" />
            )}
            {name}
          </span>
        ))}
      </div>
    </section>
  );
}
