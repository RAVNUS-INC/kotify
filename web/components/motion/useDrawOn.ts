'use client';

import { useEffect, useRef } from 'react';
import { useReducedMotion } from './useReducedMotion';

export type UseDrawOnOptions = {
  delay?: number;
  duration?: number;
};

/**
 * SVG path의 stroke-dashoffset을 이용해 "그려지는" 애니.
 * 반환된 ref를 `<path ref={ref} />`에 연결.
 * Reduced motion 시 즉시 최종 상태 (offset 0).
 */
export function useDrawOn({ delay = 0, duration = 1200 }: UseDrawOnOptions = {}) {
  const ref = useRef<SVGPathElement>(null);
  const reduce = useReducedMotion();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const len = typeof el.getTotalLength === 'function' ? el.getTotalLength() : 1000;
    el.style.strokeDasharray = `${len} ${len}`;

    if (reduce) {
      el.style.strokeDashoffset = '0';
      el.style.transition = 'none';
      return;
    }

    el.style.strokeDashoffset = String(len);
    el.style.transition = `stroke-dashoffset ${duration}ms cubic-bezier(.22,.9,.3,1) ${delay}ms`;

    let raf1 = 0;
    let raf2 = 0;
    raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => {
        if (ref.current) ref.current.style.strokeDashoffset = '0';
      });
    });
    return () => {
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
    };
  }, [delay, duration, reduce]);

  return ref;
}
