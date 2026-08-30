/**
 * The landing page's data spine — three states, never empty.
 *
 *   LIVE       — the backend answered just now
 *   LAST KNOWN — the most recent successful response, cached server-side in
 *                memory and on disk, so it survives a backend outage
 *   RECORDED   — a real snapshot from the audit history, committed to the
 *                repo, labelled with when it was recorded
 *
 * The page renders whichever it gets and labels it honestly. Nothing is ever
 * invented; an unreachable backend degrades to history, not to a skeleton.
 */

import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";

import { NextResponse } from "next/server";

import committed from "@/lib/static-snapshot.json";

export const dynamic = "force-dynamic";

const API_BASE =
  process.env.API_BASE_INTERNAL ??
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ??
  "http://localhost:8000";

const CACHE_FILE = path.join(os.tmpdir(), "skew-landing-snapshot.json");
const FETCH_TIMEOUT_MS = 3500;

interface CachedSnapshot {
  as_of: string;
  data: Record<string, unknown>;
}

let memoryCache: CachedSnapshot | null = null;

async function fetchJson(pathname: string): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE}${pathname}`, {
      signal: controller.signal,
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`${pathname} -> ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

async function readFileCache(): Promise<CachedSnapshot | null> {
  try {
    return JSON.parse(await fs.readFile(CACHE_FILE, "utf8")) as CachedSnapshot;
  } catch {
    return null;
  }
}

/** Live data ENHANCES a section; it never constitutes one. A reachable but
 *  unarmed backend answers 200 with empty payloads — each empty field falls
 *  back to the recorded snapshot, labelled per field. */
function hasContent(field: string, value: unknown): boolean {
  if (value == null) return false;
  switch (field) {
    case "universe":
      return Array.isArray(value) && value.length > 0;
    case "latest":
      return Array.isArray(value) && value.length > 0;
    case "counts":
      return Object.values(value as Record<string, number>).some((v) => v > 0);
    case "exhibit":
      return (value as { available?: boolean }).available === true;
    case "surface":
      return ((value as { slices?: unknown[] }).slices?.length ?? 0) > 0;
    case "risk":
      return (value as { equity?: number }).equity !== undefined;
    default:
      return true; // status is always meaningful live
  }
}

const RECORDED = committed as { recorded_at: string; data: Record<string, unknown> };

function compose(
  live: Record<string, unknown>,
): { data: Record<string, unknown>; fieldStates: Record<string, string> } {
  const data: Record<string, unknown> = {};
  const fieldStates: Record<string, string> = {};
  for (const field of ["status", "universe", "counts", "latest", "exhibit", "surface", "risk"]) {
    if (hasContent(field, live[field])) {
      data[field] = live[field];
      fieldStates[field] = "live";
    } else {
      data[field] = RECORDED.data[field];
      fieldStates[field] = "recorded";
    }
  }
  return { data, fieldStates };
}

export async function GET() {
  try {
    const [status, universe, counts, latest, exhibit, surface, risk] = await Promise.all([
      fetchJson("/api/status"),
      fetchJson("/api/universe"),
      fetchJson("/api/audit/counts"),
      fetchJson("/api/audit?limit=6"),
      fetchJson("/api/refusal-exhibit"),
      fetchJson("/api/surface/SPY"),
      fetchJson("/api/risk").catch(() => null),
    ]);
    const live = { status, universe, counts, latest, exhibit, surface, risk };
    const cached: CachedSnapshot = { as_of: new Date().toISOString(), data: live };
    memoryCache = cached;
    // Best-effort disk persistence — a restart of this process should not
    // forget the last good response while the backend is down.
    void fs.writeFile(CACHE_FILE, JSON.stringify(cached)).catch(() => undefined);
    const { data, fieldStates } = compose(live);
    return NextResponse.json({
      state: "live",
      as_of: cached.as_of,
      recorded_at: RECORDED.recorded_at,
      field_states: fieldStates,
      data,
    });
  } catch {
    const cached = memoryCache ?? (await readFileCache());
    if (cached) {
      memoryCache = cached;
      const { data, fieldStates } = compose(cached.data);
      // Everything that WAS live in the cache is now merely last-known.
      for (const k of Object.keys(fieldStates)) {
        if (fieldStates[k] === "live") fieldStates[k] = "last_known";
      }
      return NextResponse.json({
        state: "last_known",
        as_of: cached.as_of,
        recorded_at: RECORDED.recorded_at,
        field_states: fieldStates,
        data,
      });
    }
    // The committed snapshot: real history, honestly labelled.
    return NextResponse.json({
      state: "recorded",
      as_of: RECORDED.recorded_at,
      recorded_at: RECORDED.recorded_at,
      field_states: Object.fromEntries(
        ["status", "universe", "counts", "latest", "exhibit", "surface", "risk"].map((f) => [
          f,
          "recorded",
        ]),
      ),
      data: RECORDED.data,
    });
  }
}
