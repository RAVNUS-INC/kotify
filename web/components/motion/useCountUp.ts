'use client';

import { useEffect, useState } from 'react';
import { useReducedMotion } from './useReducedMotion';

export type UseCountUpOptions = {
  duration?: number;
  delay?: number;
};

export function useCountUp(
  target: number,
  { duration = 900, delay = 0 }: UseCountUpOptions = {},
): number {
  const [value, setValue] = useState(0);
  const reduce = useReducedMotion();

  useEffect(() => {
    if (reduce) {
      setValue(target);
      return;
    }

    let raf = 0;
    let start: number | undefined;
    const timer = window.setTimeout(() => {
      const step = (ts: number) => {
        if (start === undefined) start = ts;
        const p = Math.min((ts - start) / duration, 1);
        const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
        setValue(Math.round(target * eased));
        if (p < 1) raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    }, delay);

    return () => {
      window.clearTimeout(timer);
      cancelAnimationFrame(raf);
    };
  }, [target, duration, delay, reduce]);

  return value;
}
