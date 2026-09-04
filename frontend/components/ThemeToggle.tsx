"use client";

/**
 * Theme toggle as a quiet icon button — sun for the light target, moon for
 * dark. No arrows, no words: the icon shows where the switch goes.
 */

import { useEffect, useState } from "react";

type Theme = "dark" | "light";

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("dark");

  useEffect(() => {
    // React 19 hydration resets <html data-theme> to the server-rendered
    // value, silently undoing the pre-paint boot script. Re-apply the URL
    // override (?theme=) here, after hydration, where it sticks — the
    // screenshot and video pipelines depend on it.
    let current = document.documentElement.getAttribute("data-theme");
    const forced = window.location.search.match(/[?&]theme=(dark|light)/);
    if (forced && forced[1] !== current) {
      document.documentElement.setAttribute("data-theme", forced[1]!);
      current = forced[1]!;
    }
    if (current === "light" || current === "dark") setTheme(current);
  }, []);

  const target: Theme = theme === "dark" ? "light" : "dark";

  const flip = () => {
    document.documentElement.setAttribute("data-theme", target);
    try {
      localStorage.setItem("skew-theme", target);
    } catch {
      /* private windows */
    }
    setTheme(target);
  };

  return (
    <button
      type="button"
      onClick={flip}
      aria-label={`Switch to the ${target} theme`}
      title={`Switch to the ${target} theme`}
      className="t-fast flex h-9 w-9 items-center justify-center border border-[color:var(--line)] text-[color:var(--text-dim)] hover:border-[color:var(--text-dim)] hover:text-[color:var(--text)]"
      style={{ borderRadius: "10px" }}
    >
      {target === "light" ? (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4m11.4-11.4 1.4-1.4" />
        </svg>
      ) : (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
        </svg>
      )}
    </button>
  );
}
