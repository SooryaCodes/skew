/**
 * Server-side data for first paint — the app pages must never render their
 * empty states to a reader whose JavaScript has not run yet. Each page's
 * server component fetches the endpoints its client needs, and the payloads
 * ride into SWR as fallback data, so the first HTML already carries real
 * numbers and hydration merely takes over polling.
 *
 * The last successful response per path is cached in module memory: if the
 * backend is briefly unreachable, the page renders the cached truth labelled
 * "as of <time>" rather than a skeleton claiming nothing has happened.
 */

const API_BASE =
  process.env.API_BASE_INTERNAL ??
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ??
  "http://localhost:8000";

const FETCH_TIMEOUT_MS = 3000;

interface Cached {
  data: unknown;
  at: number; // epoch ms of the successful fetch
}

const lastGood = new Map<string, Cached>();

async function fetchJson(path: string): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      signal: controller.signal,
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`${path} -> ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

export interface SsrResult {
  /** SWR fallback map, keyed exactly as the client hooks key their requests. */
  fallback: Record<string, unknown>;
  /** Set when ANY path was served from the stale cache instead of live. */
  staleAsOf: string | null;
}

export async function ssrFallback(paths: string[]): Promise<SsrResult> {
  const fallback: Record<string, unknown> = {};
  let oldestStale: number | null = null;

  await Promise.all(
    paths.map(async (path) => {
      try {
        const data = await fetchJson(path);
        lastGood.set(path, { data, at: Date.now() });
        fallback[path] = data;
      } catch {
        const cached = lastGood.get(path);
        if (cached) {
          fallback[path] = cached.data;
          oldestStale = oldestStale === null ? cached.at : Math.min(oldestStale, cached.at);
        }
        // No cache either: the client hook keeps its own loading state — the
        // page still renders every panel that DID resolve.
      }
    }),
  );

  return {
    fallback,
    staleAsOf: oldestStale === null ? null : new Date(oldestStale).toISOString(),
  };
}
