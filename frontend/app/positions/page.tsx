import { SsrProvider } from "@/components/SsrProvider";
import { ssrFallback } from "@/lib/ssr";

import { PositionsClient } from "./PositionsClient";

export const dynamic = "force-dynamic";

export default async function PositionsPage() {
  const { fallback, staleAsOf } = await ssrFallback([
    "/api/status",
    "/api/positions",
    "/api/positions/closed",
    "/api/risk",
  ]);
  return (
    <SsrProvider fallback={fallback} staleAsOf={staleAsOf}>
      <PositionsClient />
    </SsrProvider>
  );
}
