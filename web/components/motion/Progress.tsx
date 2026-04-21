'use client';

import { useEffect, useState } from 'react';
import { useReducedMotion } from './useReducedMotion';

export type ProgressProps = {
  value: number;
  max?: number;
  color?: string;
  bg?: string;
  height?: number;
  delay?: number;
  duration?: number;
  ariaLabel?: string;
  className?: string;
};

export function Progress({
  value,
  max = 100,
  color = 'var(--brand)',
  bg = 'var(--gray-3)',
  height = 4,
  delay = 0,
  duration = 900,
  ariaLabel,
  className,
}: ProgressProps) {
  const [width, setWidth] = useState(0);
  const reduce = useReducedMotion();
  const target = (Math.min(Math.max(value, 0), max) / max) * 100;

  useEffect(() => {
    if (reduce) {
      setWidth(target);
      return;
    }
    const t = window.setTimeout(() => setWidth(target), delay);
    return () => window.clearTimeout(t);
  }, [target, delay, reduce]);

  return (
    <div
      role="progressbar"
      aria-label={ariaLabel}
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={max}
      className={className}
      style={{
        width: '100%',
        height,
        background: bg,
        borderRadius: height / 2,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          width: `${width}%`,
          height: '100%',
          background: color,
          borderRadius: height / 2,
          transition: reduce
            ? 'none'
            : `width ${duration}ms cubic-bezier(.22,.9,.3,1)`,
        }}
      />
    </div>
  );
}
