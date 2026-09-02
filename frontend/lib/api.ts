/**
 * Data access. SWR with a 5s refresh — polling, not websockets.
 *
 * At a five-minute loop interval, polling is entirely sufficient and saves half
 * a day of websocket plumbing that no judge would ever see. See
 * docs/02-TECH-STACK.md.
 *
 * The browser talks only to our FastAPI service and holds no credential. There
 * is no `NEXT_PUBLIC_` variable here carrying a secret — anything with that
 * prefix ships in the client bundle and is readable by anyone.
 */

import useSWR, { type SWRResponse } from "swr";

import type {
  AuditQueryResult,
  Candidate,
  ClosedPosition,
  CycleStatus,
  RefusalExhibit,
  Surface,
  Decision,
  Position,
  RiskAuthority,
  SessionSummary,
  SystemStatus,
  VolState,
  VrpHistory,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "http://localhost:8000";

const REFRESH_MS = 5000;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function fetcher<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new ApiError(`${path} returned ${response.status}`, response.status);
  }
  return (await response.json()) as T;
}

/** Named `usePoll` so the rules-of-hooks lint recognises it as a custom hook. */
function usePoll<T>(path: string | null, refreshMs = REFRESH_MS): SWRResponse<T, ApiError> {
  return useSWR<T, ApiError>(path, fetcher, {
    refreshInterval: refreshMs,
    revalidateOnFocus: true,
    keepPreviousData: true,
    shouldRetryOnError: true,
    errorRetryInterval: 8000,
  });
}

export const useStatus = () => usePoll<SystemStatus>("/api/status", 10000);
export const useUniverse = () => usePoll<VolState[]>("/api/universe");
export const useCandidates = () => usePoll<Candidate[]>("/api/candidates");
export const useRisk = () => usePoll<RiskAuthority>("/api/risk");
export const usePositions = () => usePoll<Position[]>("/api/positions", 10000);
export const useClosedPositions = () =>
  usePoll<ClosedPosition[]>("/api/positions/closed", 30000);
export const useAudit = (limit = 40) => usePoll<Decision[]>(`/api/audit?limit=${limit}`);
export const useAuditCounts = () =>
  usePoll<Record<string, number>>("/api/audit/counts", 15000);
// The /audit page: the query string IS the page state, so the URL is the key.
export const useAuditQuery = (qs: string) =>
  usePoll<AuditQueryResult>(`/api/audit/query${qs ? `?${qs}` : ""}`, 30000);
export const useVrpHistory = (symbol: string | null) =>
  usePoll<VrpHistory>(symbol ? `/api/vrp-history/${symbol}` : null, 60000);
// Fast poll: this is what animates the RUN CYCLE NOW control while it thinks.
export const useCycleStatus = () => usePoll<CycleStatus>("/api/cycle/status", 1500);
export const useSession = () => usePoll<SessionSummary>("/api/session", 15000);
export const useRefusalExhibit = () =>
  usePoll<RefusalExhibit>("/api/refusal-exhibit", 60000);
export const useSurface = (symbol: string) =>
  usePoll<Surface>(`/api/surface/${symbol}`, 15 * 60 * 1000);
