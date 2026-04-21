'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { useReducedMotion } from './useReducedMotion';

export type AnimatedBarsProps = {
  data: ReadonlyArray<number>;
  max?: number;
  height?: number;
  gap?: number;
  color?: string;
  labels?: ReadonlyArray<ReactNode>;
  staggerStep?: number;
  duration?: number;
};

export function AnimatedBars({
  data,
  max,
  height = 100,
  gap = 6,
  color = 'var(--brand)',
  labels,
  staggerStep = 40,
  duration = 700,
}: AnimatedBarsProps) {
  const reduce = useReducedMotion();
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (reduce) {
      setShow(true);
      return;
    }
    const raf = requestAnimationFrame(() => setShow(true));
    return () => cancelAnimationFrame(raf);
  }, [reduce]);

  const maxV = max ?? (Math.max(...data, 0) || 1);

  return (
    <div
      className="flex items-end"
      style={{ gap, height }}
      role="img"
      aria-label="bar chart"
    >
      {data.map((v, i) => {
        const pct = (v / maxV) * 100;
        return (
          <div key={i} className="flex flex-1 flex-col items-center gap-1">
            <div className="flex w-full flex-1 items-end">
              <div
                style={{
                  width: '100%',
                  height: `${pct}%`,
                  background: color,
                  borderRadius: '2px 2px 0 0',
                  transformOrigin: 'bottom',
                  transform: show ? 'scaleY(1)' : 'scaleY(0)',
                  transition: reduce
                    ? 'none'
                    : `transform ${duration}ms cubic-bezier(.22,.9,.3,1)`,
                  transitionDelay: reduce ? '0ms' : `${i * staggerStep}ms`,
                }}
              />
            </div>
            {labels?.[i] != null && (
              <div className="font-mono text-[10px] text-ink-dim">{labels[i]}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}
