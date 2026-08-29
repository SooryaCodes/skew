"use client";

/**
 * Theme toggle. data-theme lives on <html>, set before paint by the boot
 * script in layout.tsx; this button just flips it and persists the choice.
 * Default (no stored choice) follows prefers-color-scheme.
 */

import { useEffect, useState } from "react";

type Theme = "dark" | "light";

function currentTheme(): Theme {
  return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}

export function ThemeToggle() {
  // null until mounted, so SSR and the first client render agree.
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    setTheme(currentTheme());
  }, []);

  const flip = () => {
    const next: Theme = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("skew-theme", next);
    } catch {
      // Private windows can refuse storage; the flip still applies for the session.
    }
    setTheme(next);
  };

  return (
    <button
      type="button"
      onClick={flip}
      aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
      className="mono t-fast px-1 text-[10px] uppercase tracking-wider text-[color:var(--text-dim)] hover:text-[color:var(--text)]"
    >
      {theme === null ? "…" : theme === "dark" ? "light" : "dark"}
    </button>
  );
}
