/**
 * Phase 00 placeholder — confirms the palette, the three type faces and the
 * panel treatment render correctly before any real component is built.
 * Replaced by the desk in Phase 06.
 */

const SWATCHES = [
  { name: "--ground", value: "var(--ground)", note: "deep indigo-black, has a temperature" },
  { name: "--surface", value: "var(--surface)", note: "raised panels" },
  { name: "--line", value: "var(--line)", note: "hairlines, grid, dividers" },
  { name: "--text", value: "var(--text)", note: "primary" },
  { name: "--muted", value: "var(--muted)", note: "labels, axes, secondary" },
  { name: "--rich", value: "var(--rich)", note: "vol is EXPENSIVE — sell premium" },
  { name: "--cheap", value: "var(--cheap)", note: "vol is CHEAP — buy premium" },
  { name: "--breach", value: "var(--breach)", note: "a gate FAILED — nothing else, ever" },
] as const;

export default function Home() {
  return (
    <main className="mx-auto max-w-4xl px-6 py-16">
      <p className="mono text-[color:var(--muted)] text-xs uppercase tracking-widest">
        Phase 00 — scaffold
      </p>
      <h1 className="font-display mt-3 text-[length:var(--fs-xl)] leading-none">SKEW</h1>
      <p className="mt-4 max-w-xl text-[color:var(--muted)]">
        An options desk that never predicts price direction. It measures the gap between
        implied and realized volatility and takes defined-risk positions into it — with
        every trade gated by a deterministic stress test before the model is allowed to act.
      </p>

      <section className="mt-12">
        <h2 className="font-display text-[length:var(--fs-md)]">Palette</h2>
        <div className="panel mt-4 divide-y divide-[color:var(--line)]">
          {SWATCHES.map((s) => (
            <div key={s.name} className="flex items-center gap-4 px-4 py-3">
              <span
                className="h-6 w-10 shrink-0 border border-[color:var(--line)]"
                style={{ background: s.value, borderRadius: "var(--radius)" }}
              />
              <span className="mono w-28 shrink-0 text-xs">{s.name}</span>
              <span className="text-[color:var(--muted)] text-xs">{s.note}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="mt-12">
        <h2 className="font-display text-[length:var(--fs-md)]">Type</h2>
        <div className="panel mt-4 space-y-3 p-4">
          <p className="font-display text-[length:var(--fs-lg)]">Archivo — display</p>
          <p className="text-[length:var(--fs-base)]">
            Instrument Sans — body. Gate reasons and model rationale render in this face.
          </p>
          <p className="mono text-[length:var(--fs-base)]">
            IBM Plex Mono — data. 0123456789 −$1,240.00 +14.2σ
          </p>
          <p className="contract text-[length:var(--fs-sm)] text-[color:var(--muted)]">
            spy250919p00580000
          </p>
        </div>
      </section>

      <section className="mt-12">
        <h2 className="font-display text-[length:var(--fs-md)]">Two poles</h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div className="panel p-4">
            <p className="mono text-xs uppercase tracking-widest text-[color:var(--rich)]">
              vol rich
            </p>
            <p className="mono mt-2 text-[length:var(--fs-lg)] text-[color:var(--rich)]">+14.2</p>
            <p className="mt-1 text-xs text-[color:var(--muted)]">
              IV above realized. The market is overpaying for fear — sell premium.
            </p>
          </div>
          <div className="panel p-4">
            <p className="mono text-xs uppercase tracking-widest text-[color:var(--cheap)]">
              vol cheap
            </p>
            <p className="mono mt-2 text-[length:var(--fs-lg)] text-[color:var(--cheap)]">−3.1</p>
            <p className="mt-1 text-xs text-[color:var(--muted)]">
              Movement is underpriced relative to what actually happened — buy premium.
            </p>
          </div>
        </div>
      </section>

      <p className="mono mt-16 text-xs text-[color:var(--muted)]">
        paper trading only · no live code path exists
      </p>
    </main>
  );
}
