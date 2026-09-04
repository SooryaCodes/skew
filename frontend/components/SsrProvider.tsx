"use client";

/**
 * Hands the server-fetched payloads to SWR as fallback data, so the client
 * hooks render real numbers on first paint and simply take over polling.
 * When the server had to serve from its stale cache, a quiet "as of" line
 * says so — and disappears the moment a live response lands.
 */

import { useEffect, useState } from "react";
import { SWRConfig } from "swr";

import { useStatus } from "@/lib/api";
import { clockTime } from "@/lib/format";

function StaleNotice({ asOf }: { asOf: string }) {
  const { data, error } = useStatus();
  const [liveAgain, setLiveAgain] = useState(false);
  useEffect(() => {
    // The fallback satisfies the first render; a real network success after
    // mount means we are current again and the label would be a lie.
    if (data && !error) {
      const timer = setTimeout(() => setLiveAgain(true), 1500);
      return () => clearTimeout(timer);
    }
    return undefined;
  }, [data, error]);
  if (liveAgain) return null;
  return (
    <p
      className="mono border-b border-[color:var(--line)] bg-[color:var(--panel)] px-4 py-1.5 text-[12px] text-[color:var(--text-dim)]"
      role="status"
    >
      as of {clockTime(asOf)} — cached while the backend reconnects
    </p>
  );
}

/** React 19 hydration resets <html data-theme> to the server value, undoing
 *  the pre-paint boot script's ?theme= override. Shot mode hides the header
 *  (and the theme toggle with it), so the always-mounted provider re-applies
 *  the override — the screenshot and video pipelines depend on it. */
function useThemeOverride() {
  useEffect(() => {
    const forced = window.location.search.match(/[?&]theme=(dark|light)/);
    if (forced && document.documentElement.getAttribute("data-theme") !== forced[1]) {
      document.documentElement.setAttribute("data-theme", forced[1]!);
    }
  }, []);
}

export function SsrProvider({
  fallback,
  staleAsOf,
  children,
}: {
  fallback: Record<string, unknown>;
  staleAsOf: string | null;
  children: React.ReactNode;
}) {
  useThemeOverride();
  return (
    <SWRConfig value={{ fallback }}>
      {staleAsOf && <StaleNotice asOf={staleAsOf} />}
      {children}
    </SWRConfig>
  );
}
