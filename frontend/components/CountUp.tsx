"use client";

/**
 * A number that counts up to its live value when scrolled into view — 600ms,
 * ease-out, once. Server markup and reduced-motion readers get the final
 * value immediately; the count never runs on data refresh, only on reveal.
 */

import { useEffect, useRef, useState } from "react";

import { prefersReducedMotion, useInView } from "@/lib/useInView";

interface Props {
  value: number;
  format: (n: number) => string;
  className?: string;
  style?: React.CSSProperties;
}

export function CountUp({ value, format, className, style }: Props) {
  const { ref, inView } = useInView<HTMLSpanElement>(0.4);
  const [shown, setShown] = useState(value);
  const animated = useRef(false);
  const animating = useRef(false);

  useEffect(() => {
    if (!inView || animated.current) return;
    animated.current = true;
    if (prefersReducedMotion()) return;
    const target = value;
    const start = performance.now();
    animating.current = true;
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / 600);
      const eased = 1 - (1 - t) ** 3;
      setShown(target * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
      else animating.current = false;
    };
    raf = requestAnimationFrame(tick);
    return () => {
      animating.current = false;
      cancelAnimationFrame(raf);
    };
  }, [inView, value]);

  // The number always tracks the live value except during the one count-up —
  // a value that arrives before the animation (or when observers never fire)
  // must never leave a stale zero on screen.
  useEffect(() => {
    if (!animating.current) setShown(value);
  }, [value]);

  return (
    <span ref={ref} className={className} style={style}>
      {format(shown)}
    </span>
  );
}
