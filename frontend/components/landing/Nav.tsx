"use client";

/**
 * Floating pill nav: a single rounded bar hovering over the page, panel at
 * 85% with backdrop blur. Narrow by design — wordmark, three anchors, theme,
 * one CTA. Anchors still work with JavaScript disabled.
 */

import Link from "next/link";

import { Logo } from "@/components/Logo";
import { ThemeToggle } from "@/components/ThemeToggle";

const LINKS = [
  { href: "/#how-it-works", label: "How it works" },
  { href: "/#architecture", label: "Architecture" },
  { href: "/mcp", label: "MCP" },
  { href: "/#faq", label: "FAQ" },
];

export function Nav() {
  return (
    <header className="fixed inset-x-0 top-4 z-40 px-4">
      <div
        className="mx-auto flex h-14 w-full max-w-3xl items-center justify-between gap-4 border border-[color:var(--line)] pl-4 pr-2"
        style={{
          borderRadius: "999px",
          background: "color-mix(in srgb, var(--panel) 85%, transparent)",
          backdropFilter: "blur(12px)",
          WebkitBackdropFilter: "blur(12px)",
        }}
      >
        <Link href="/" aria-label="SKEW — home">
          <Logo size={26} />
        </Link>
        <nav className="hidden gap-6 text-[14px] font-medium sm:flex" aria-label="Page">
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
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <Link
            href="/desk"
            className="btn-3d t-fast bg-[color:var(--accent)] px-4 py-2 text-[14px] font-semibold text-white"
            style={{ borderRadius: "999px" }}
          >
            Enter the desk
          </Link>
        </div>
      </div>
    </header>
  );
}
