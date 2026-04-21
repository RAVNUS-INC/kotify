'use client';

import { useEffect, useState, type CSSProperties } from 'react';
import { useReducedMotion } from './useReducedMotion';

export type UseRiseOptions = {
  delay?: number;
  y?: number;
  duration?: number;
};

export type UseRiseResult = {
  shown: boolean;
  style: CSSProperties;
};

export function useRise({
  delay = 0,
  y = 8,
  duration = 400,
}: UseRiseOptions = {}): UseRiseResult {
  const [shown, setShown] = useState(false);
  const reduce = useReducedMotion();

  useEffect(() => {
    if (reduce) {
      setShown(true);
      return;
    }
    const t = window.setTimeout(() => setShown(true), delay);
    return () => window.clearTimeout(t);
  }, [delay, reduce]);

  return {
    shown,
    style: {
      opacity: shown ? 1 : 0,
      transform: shown ? 'translateY(0)' : `translateY(${y}px)`,
      transition: reduce
        ? 'none'
        : `opacity ${duration}ms ease, transform ${duration}ms cubic-bezier(.22,.9,.3,1)`,
      willChange: 'opacity, transform',
    },
  };
}
