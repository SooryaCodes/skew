"use client";

/**
 * Sticky nav, 64px. Transparent over the hero; after ~100px of scroll it gains
 * --panel at 85% with backdrop blur and a 1px bottom border. Centre links
 * scroll to their sections (native anchors — Lenis smooths them when active,
 * and they still work with JavaScript disabled).
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { ThemeToggle } from "@/components/ThemeToggle";

const LINKS = [
  { href: "#how-it-works", label: "How it works" },
  { href: "#architecture", label: "Architecture" },
  { href: "#faq", label: "FAQ" },
];

export function Nav() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 100);
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className="fixed inset-x-0 top-0 z-40 h-16"
      style={{
        background: scrolled
          ? "color-mix(in srgb, var(--panel) 85%, transparent)"
          : "transparent",
        backdropFilter: scrolled ? "blur(10px)" : "none",
        WebkitBackdropFilter: scrolled ? "blur(10px)" : "none",
        borderBottom: scrolled ? "1px solid var(--line)" : "1px solid transparent",
        transition: "background 250ms ease, border-color 250ms ease",
      }}
    >
      <div className="mx-auto flex h-full w-full max-w-6xl items-center justify-between px-6">
        <a href="#" className="font-display text-[length:var(--fs-md)]">
          SKEW
        </a>
        <nav className="mono hidden gap-7 text-[10px] uppercase tracking-widest sm:flex" aria-label="Page">
          {LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="t-fast text-[color:var(--text-dim)] hover:text-[color:var(--text)]"
            >
              {link.label}
            </a>
          ))}
        </nav>
        <div className="flex items-center gap-4">
          <ThemeToggle />
          <Link
            href="/desk"
            className="t-fast mono border border-[color:var(--brass)] bg-[color:var(--brass)] px-3.5 py-1.5 text-[10px] uppercase tracking-widest text-[color:var(--ground)] hover:bg-transparent hover:text-[color:var(--text)]"
            style={{ borderRadius: "var(--radius)" }}
          >
            Enter the desk
          </Link>
        </div>
      </div>
    </header>
  );
}
