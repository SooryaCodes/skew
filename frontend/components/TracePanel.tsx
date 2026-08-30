"use client";

/**
 * The decision trace — the reasoning chain behind one audit entry, as a
 * vertical sequence: SCAN → MEASURE → CLASSIFY → BUILD → GATE, then OUTCOME
 * for a refusal or SELECT → EXECUTE for a fill.
 *
 * Every value is REAL recorded data from that cycle, read from the decision's
 * stored trace — never recomputed. Where an older decision predates the trace
 * schema, the step says "not recorded" rather than inventing a plausible
 * number.
 *
 * The stopping step is the story: a failing gate is the only oxide in the
 * panel, everything before it verdigris, and everything after renders at 35%
 * opacity — the chain visibly stops.
 */

import { num, vol, volPoints } from "@/lib/format";
import type { Decision, GateResult, StressCell } from "@/lib/types";

import { StressGrid } from "./StressGrid";

type StepTone = "done" | "fail" | "stop" | "after" | "missing";

interface Step {
  label: string;
  tone: StepTone;
  body: React.ReactNode;
}

const TONE: Record<StepTone, { marker: string; opacity: number }> = {
  done: { marker: "var(--verdigris)", opacity: 1 },
  fail: { marker: "var(--oxide)", opacity: 1 },
  stop: { marker: "var(--brass)", opacity: 1 },
  after: { marker: "var(--line)", opacity: 0.35 },
  missing: { marker: "var(--line)", opacity: 0.6 },
};

function Mono({ children }: { children: React.ReactNode }) {
  return <span className="mono text-[12px] text-[color:var(--text)]">{children}</span>;
}

function NotRecorded() {
  return (
    <p className="mono text-[11px] text-[color:var(--text-dim)]">
      not recorded — this decision predates the trace schema
    </p>
  );
}

function GateStep({
  gates,
  grid,
  maxLoss,
}: {
  gates: GateResult[];
  grid?: StressCell[];
  maxLoss?: number;
}) {
  const failed = gates.filter((g) => !g.passed && !g.skipped);
  return (
    <div>
      <p className="mono flex flex-wrap gap-x-3 gap-y-1 text-[12px]">
        {gates.map((g) => (
          <span key={g.gate} className="flex items-center gap-1">
            <span
              style={{
                color: g.skipped
                  ? "var(--text-dim)"
                  : g.passed
                    ? "var(--verdigris)"
                    : "var(--oxide)",
              }}
            >
              {g.skipped ? "—" : g.passed ? "✓" : "✗"}
            </span>
            <span className="text-[color:var(--text-dim)]">{g.gate}</span>
          </span>
        ))}
      </p>
      {/* The failing gate expands with its complete reason. */}
      {failed.map((g) => (
        <div key={g.gate} className="mt-2 border-l-2 pl-3" style={{ borderColor: "var(--oxide)" }}>
          <p className="mono text-[10px] uppercase tracking-wider text-[color:var(--text-dim)]">
            ↳ {g.gate} failed
          </p>
          <p className="mt-1 text-[12px] leading-relaxed text-[color:var(--text)]">{g.reason}</p>
          {g.gate === "stress" && grid && grid.length > 0 && (
            <div className="mt-3 max-w-md">
              <StressGrid cells={grid} maxLoss={maxLoss ?? 1} refused />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/** Build the step sequence from one recorded decision. */
function buildSteps(decision: Decision): Step[] {
  const detail = decision.detail as Record<string, unknown>;
  const trace = (detail.trace ?? {}) as Record<string, Record<string, unknown>>;
  const gates = (detail.gates as GateResult[] | undefined) ?? [];
  const grid = detail.stress_grid as StressCell[] | undefined;
  const scan = trace.scan;
  const measure = trace.measure;
  const classify = trace.classify;
  const build = trace.build;

  // Where did the chain stop, and how?
  const gateFailed = gates.some((g) => !g.passed && !g.skipped);
  const abstainedAtClassify = classify?.regime === "ABSTAIN";
  const scanFailed = Boolean(scan && "error" in scan);
  const executed = decision.action === "EXECUTED";
  const isClose = executed && !detail.legs && gates.length === 0;

  const steps: Step[] = [];
  const push = (label: string, tone: StepTone, body: React.ReactNode) =>
    steps.push({ label, tone, body });

  // 1 SCAN
  if (scanFailed) {
    push("scan", "fail", <Mono>{String(scan!.error)}</Mono>);
  } else if (scan) {
    push(
      "scan",
      "done",
      <Mono>
        {String(scan.symbol)} {num(Number(scan.spot), 2)} · chain fetched,{" "}
        {String(scan.contracts)} contracts
      </Mono>,
    );
  } else {
    push("scan", "missing", <NotRecorded />);
  }

  const afterScan: StepTone = scanFailed ? "after" : "done";

  // 2 MEASURE
  if (measure && !scanFailed) {
    push(
      "measure",
      "done",
      <Mono>
        iv {vol(Number(measure.iv_atm))} · rv {vol(Number(measure.rv_20))} · vrp{" "}
        {volPoints(Number(measure.vrp))} · term {volPoints(Number(measure.term_slope))}{" "}
        {Number(measure.term_slope) >= 0 ? "contango" : "backwardation"}
      </Mono>,
    );
  } else {
    push("measure", scanFailed ? "after" : "missing", scanFailed ? null : <NotRecorded />);
  }

  // 3 CLASSIFY — an ABSTAIN regime is where that chain legitimately stops.
  if (classify && !scanFailed) {
    push(
      "classify",
      abstainedAtClassify ? "stop" : "done",
      <div>
        <Mono>{String(classify.regime)}</Mono>
        <p className="mt-1 text-[12px] leading-relaxed text-[color:var(--text)]">
          {String(classify.note)}
        </p>
      </div>,
    );
  } else {
    push("classify", scanFailed ? "after" : "missing", scanFailed ? null : <NotRecorded />);
  }

  const pastClassify = scanFailed || abstainedAtClassify;

  // 4 BUILD
  if (build && !pastClassify) {
    const kinds = (build.kinds as string[]) ?? [];
    push(
      "build",
      "done",
      <Mono>
        {String(build.count)} structure{Number(build.count) === 1 ? "" : "s"} constructed
        {kinds.length > 0 && ` — ${kinds.map((k) => k.replaceAll("_", " ").toLowerCase()).join(", ")}`}
        , strikes by delta target
      </Mono>,
    );
  } else {
    push("build", pastClassify ? "after" : "missing", pastClassify ? null : <NotRecorded />);
  }

  // 5 GATE
  if (gates.length > 0 && !pastClassify) {
    push(
      "gate",
      gateFailed ? "fail" : "done",
      <GateStep gates={gates} grid={grid} maxLoss={detail.max_loss as number | undefined} />,
    );
  } else if (!pastClassify && build) {
    const survivors = ((build.survivors as string[]) ?? []).length;
    push(
      "gate",
      "done",
      <Mono>
        {survivors} of {String(build.count)} candidates survived the chain — per-candidate
        results live on each refusal&rsquo;s own trace
      </Mono>,
    );
  } else {
    push("gate", pastClassify ? "after" : "missing", pastClassify ? null : <NotRecorded />);
  }

  // 6+ — how it ended.
  if (executed && !isClose) {
    push(
      "select",
      "done",
      <div>
        <Mono>the bounded selector chose {String(detail.kind ?? decision.structure_id)}</Mono>
        {decision.model_rationale && (
          <p className="mt-1 border-l border-[color:var(--line)] pl-2 text-[12px] italic leading-relaxed text-[color:var(--text)]">
            {decision.model_rationale}
          </p>
        )}
      </div>,
    );
    push(
      "execute",
      "done",
      <div>
        <Mono>order {decision.order_id ?? "—"}</Mono>
        {Array.isArray(detail.legs) && (
          <p className="contract mt-1 text-[10px] text-[color:var(--text-dim)]">
            {(detail.legs as string[]).join(" · ")}
          </p>
        )}
        <p className="mono mt-1 text-[11px] text-[color:var(--text-dim)]">
          one atomic mleg order · limit {num(Number(detail.limit_price ?? 0), 2)} · status{" "}
          {String(detail.status ?? "submitted")}
        </p>
      </div>,
    );
  } else if (executed && isClose) {
    push("execute", "done", <Mono>{decision.reason}</Mono>);
  } else if (decision.action === "REFUSED") {
    push(
      "outcome",
      "after",
      <Mono>REFUSED — {gateFailed ? "the gate chain stopped this structure" : decision.reason}</Mono>,
    );
  } else {
    // Abstention: the selector, the classifier, or the chain upstream.
    const tone: StepTone = pastClassify || gateFailed ? "after" : "stop";
    push(
      "outcome",
      tone,
      <div>
        <Mono>ABSTAINED — {decision.reason}</Mono>
        {decision.model_rationale && (
          <p className="mt-1 border-l border-[color:var(--line)] pl-2 text-[12px] italic leading-relaxed text-[color:var(--text)]">
            {decision.model_rationale}
          </p>
        )}
      </div>,
    );
  }

  // Everything after a hard failure dims — the chain visibly stops.
  const failIndex = steps.findIndex((s) => s.tone === "fail");
  if (failIndex !== -1) {
    for (let i = failIndex + 1; i < steps.length; i += 1) {
      if (steps[i]!.tone === "done" || steps[i]!.tone === "stop") steps[i]!.tone = "after";
    }
  }
  void afterScan;
  return steps;
}

export function TracePanel({ decision }: { decision: Decision }) {
  const steps = buildSteps(decision);

  return (
    <ol className="space-y-0" aria-label="Decision trace">
      {steps.map((step, i) => {
        const tone = TONE[step.tone];
        return (
          <li key={step.label} className="flex gap-4" style={{ opacity: tone.opacity }}>
            {/* the spine */}
            <div className="flex flex-col items-center">
              <span
                className="mono flex h-7 w-7 shrink-0 items-center justify-center border text-[10px]"
                style={{
                  borderColor: tone.marker,
                  color: "var(--text)",
                  borderRadius: "var(--radius)",
                  background:
                    step.tone === "fail"
                      ? "color-mix(in srgb, var(--oxide) 18%, var(--panel))"
                      : "var(--panel)",
                }}
                aria-hidden
              >
                {i + 1}
              </span>
              {i < steps.length - 1 && (
                <span className="w-px flex-1" style={{ background: "var(--line)" }} aria-hidden />
              )}
            </div>
            <div className="min-w-0 flex-1 pb-6">
              <p
                className="mono mb-1 text-[10px] uppercase tracking-widest"
                style={{
                  color:
                    step.tone === "fail"
                      ? "var(--oxide)"
                      : step.tone === "stop"
                        ? "var(--text)"
                        : "var(--text-dim)",
                }}
              >
                {step.label}
              </p>
              {step.body}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
