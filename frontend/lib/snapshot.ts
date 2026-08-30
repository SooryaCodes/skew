"use client";

/**
 * Client side of the three-state data spine. One poll against our own
 * server-side snapshot route; if even THAT fails (frontend server dead mid-
 * session), the last successful payload is kept. Components receive data plus
 * a provenance label and render both.
 */

import useSWR from "swr";

import type {
  Decision,
  RefusalExhibit,
  RiskAuthority,
  Surface,
  SystemStatus,
  VolState,
} from "./types";

export type SnapshotState = "live" | "last_known" | "recorded";

export interface Snapshot {
  state: SnapshotState;
  as_of: string;
  recorded_at?: string;
  /** Per-field provenance: an unarmed-but-reachable backend serves live status
   *  while its empty universe falls back to the recorded history. */
  field_states?: Record<string, SnapshotState>;
  data: {
    status?: SystemStatus;
    universe?: VolState[];
    counts?: Record<string, number>;
    latest?: Decision[];
    exhibit?: RefusalExhibit;
    surface?: Surface;
    risk?: RiskAuthority;
  };
}

async function fetchSnapshot(url: string): Promise<Snapshot> {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`snapshot ${response.status}`);
  return (await response.json()) as Snapshot;
}

export function useSnapshot() {
  return useSWR<Snapshot>("/api/snapshot", fetchSnapshot, {
    refreshInterval: 15000,
    revalidateOnFocus: true,
    keepPreviousData: true,
    shouldRetryOnError: true,
    errorRetryInterval: 10000,
  });
}

/** Provenance for ONE field of the snapshot — the label a section renders. */
export function fieldProvenance(snapshot: Snapshot, field: string): string {
  const state = snapshot.field_states?.[field] ?? snapshot.state;
  const asOf = state === "recorded" ? (snapshot.recorded_at ?? snapshot.as_of) : snapshot.as_of;
  return provenanceLabel(state, asOf);
}

/** "reading live from the desk" / "as of 14:43" / "recorded 30 Aug" */
export function provenanceLabel(state: SnapshotState, asOf: string): string {
  if (state === "live") return "reading live from the desk";
  const when = new Date(asOf);
  if (state === "last_known") {
    return `as of ${when.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })} · last known`;
  }
  return `recorded ${when.toLocaleDateString("en-US", { day: "numeric", month: "short" })} · from the audit history`;
}
