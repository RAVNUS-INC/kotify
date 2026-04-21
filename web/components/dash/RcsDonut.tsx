'use client';

import { useEffect, useState } from 'react';
import { Counter, useReducedMotion } from '@/components/motion';

export type RcsDonutProps = {
  /** 0-100 */
  rate: number;
  size?: number;
  strokeWidth?: number;
  delay?: number;
  duration?: number;
};

export function RcsDonut({
  rate,
  size = 160,
  strokeWidth = 10,
  delay = 300,
  duration = 1000,
}: RcsDonutProps) {
  const r = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * r;
  const target = circumference - (Math.min(Math.max(rate, 0), 100) / 100) * circumference;
  const [offset, setOffset] = useState(circumference);
  const reduce = useReducedMotion();

  useEffect(() => {
    if (reduce) {
      setOffset(target);
      return;
    }
    const t = window.setTimeout(() => setOffset(target), delay);
    return () => window.clearTimeout(t);
  }, [target, delay, reduce]);

  return (
    <div
      className="relative inline-flex items-center justify-center"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`RCS 도달률 ${rate.toFixed(1)}%`}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        style={{ transform: 'rotate(-90deg)' }}
        aria-hidden
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="rgba(255,255,255,0.14)"
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{
            transition: reduce
              ? 'none'
              : `stroke-dashoffset ${duration}ms cubic-bezier(.22,.9,.3,1) ${delay}ms`,
          }}
        />
      </svg>
      <Counter
        value={rate}
        format="percent"
        delay={delay + 100}
        className="absolute text-4xl font-semibold tracking-[-0.03em] tabular-nums"
      />
    </div>
  );
}
