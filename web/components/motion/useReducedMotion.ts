'use client';

import { useEffect, useState } from 'react';

/**
 * `prefers-reduced-motion: reduce` 매체 질의를 구독한다.
 * SSR 시 `false`로 렌더되며, mount 이후 실제 값으로 갱신.
 */
export function useReducedMotion(): boolean {
  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReduce(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setReduce(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  return reduce;
}
