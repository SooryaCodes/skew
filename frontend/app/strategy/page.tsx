import { SsrProvider } from "@/components/SsrProvider";
import { ssrFallback } from "@/lib/ssr";

import { StrategyClient } from "./StrategyClient";

export const dynamic = "force-dynamic";

export default async function StrategyPage() {
  const { fallback, staleAsOf } = await ssrFallback([
    "/api/status",
    "/api/strategy",
    "/api/risk",
  ]);
  return (
    <SsrProvider fallback={fallback} staleAsOf={staleAsOf}>
      <StrategyClient />
    </SsrProvider>
  );
}
