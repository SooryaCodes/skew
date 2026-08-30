"use client";

/**
 * Scroll reveal: opacity plus a 4px horizontal drift, staggered 40ms per line
 * via --reveal-delay. One-shot. The .js CSS gate keeps content visible for
 * no-JS readers, and prefers-reduced-motion makes every reveal instant.
 */

import { useInView } from "@/lib/useInView";

interface Props {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}

export function Reveal({ children, delay = 0, className }: Props) {
  const { ref, inView } = useInView<HTMLDivElement>(0.2);
  return (
    <div
      ref={ref}
      className={`reveal${inView ? " revealed" : ""}${className ? ` ${className}` : ""}`}
      style={{ "--reveal-delay": `${delay}ms` } as React.CSSProperties}
    >
      {children}
    </div>
  );
}
