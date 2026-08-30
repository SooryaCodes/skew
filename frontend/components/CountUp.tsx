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

  useEffect(() => {
    if (!inView || animated.current) return;
    animated.current = true;
    if (prefersReducedMotion()) return;
    const target = value;
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / 600);
      const eased = 1 - (1 - t) ** 3;
      setShown(target * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [inView, value]);

  // After the one animation, track the live value directly.
  const display = animated.current && shown === value ? value : shown;
  useEffect(() => {
    if (animated.current) setShown(value);
  }, [value]);

  return (
    <span ref={ref} className={className} style={style}>
      {format(display)}
    </span>
  );
}
