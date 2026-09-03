import { SsrProvider } from "@/components/SsrProvider";
import { ssrFallback } from "@/lib/ssr";

import { AuditClient } from "./AuditClient";

export const dynamic = "force-dynamic";

/** Mirrors AuditClient's toQueryString for the API key, so the server-fetched
 *  payload lands under the exact key the client hook will ask for. */
function apiQuery(params: Record<string, string | string[] | undefined>): string {
  const qs = new URLSearchParams();
  const get = (k: string) => {
    const v = params[k];
    return typeof v === "string" ? v : undefined;
  };
  const action = get("action");
  if (action) qs.set("action", action);
  const symbols = get("symbols");
  if (symbols) qs.set("symbols", symbols);
  const gate = get("gate");
  if (gate) qs.set("gate", gate);
  const q = get("q");
  if (q) qs.set("q", q);
  const from = get("from");
  if (from) qs.set("date_from", from);
  const to = get("to");
  if (to) qs.set("date_to", to);
  const sort = get("sort");
  if (sort && sort !== "desc") qs.set("sort", sort);
  if (get("grouped") === "0") qs.set("grouped", "0");
  qs.set("limit", "100");
  return qs.toString();
}

export default async function AuditPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const urlSearch = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (typeof value === "string") urlSearch.set(key, value);
  }
  const { fallback, staleAsOf } = await ssrFallback([
    "/api/status",
    "/api/audit/counts",
    `/api/audit/query?${apiQuery(params)}`,
  ]);
  return (
    <SsrProvider fallback={fallback} staleAsOf={staleAsOf}>
      <AuditClient initialSearch={urlSearch.toString()} />
    </SsrProvider>
  );
}
