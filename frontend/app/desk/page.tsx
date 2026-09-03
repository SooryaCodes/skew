import { SsrProvider } from "@/components/SsrProvider";
import { ssrFallback } from "@/lib/ssr";

import { DeskClient } from "./DeskClient";

// The first HTML must carry real numbers: a reader with slow or disabled
// JavaScript (or a preview crawler) sees the actual desk, not empty states
// on a system with thousands of decisions. See lib/ssr.ts.
export const dynamic = "force-dynamic";

export default async function DeskPage() {
  const { fallback, staleAsOf } = await ssrFallback([
    "/api/status",
    "/api/universe",
    "/api/candidates",
    "/api/risk",
    "/api/audit?limit=60",
    "/api/audit?limit=1",
    "/api/audit/counts",
    "/api/session",
    "/api/positions/closed",
  ]);
  // The session sentence needs the refusals-by-gate breakdown for the session
  // window — its key depends on the session date we just fetched.
  const session = fallback["/api/session"] as { session_date?: string } | undefined;
  if (session?.session_date) {
    const extra = await ssrFallback([
      `/api/audit/query?action=REFUSED&date_from=${session.session_date}&limit=1`,
    ]);
    Object.assign(fallback, extra.fallback);
  }
  return (
    <SsrProvider fallback={fallback} staleAsOf={staleAsOf}>
      <DeskClient />
    </SsrProvider>
  );
}
