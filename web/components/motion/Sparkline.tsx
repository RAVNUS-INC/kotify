'use client';

import { useId } from 'react';
import { useDrawOn } from './useDrawOn';
import { useReducedMotion } from './useReducedMotion';

export type SparklineProps = {
  data: ReadonlyArray<number>;
  width?: number;
  height?: number;
  color?: string;
  strokeWidth?: number;
  delay?: number;
  duration?: number;
  fill?: boolean;
  className?: string;
};

export function Sparkline({
  data,
  width = 120,
  height = 32,
  color = 'var(--brand)',
  strokeWidth = 1.5,
  delay = 0,
  duration = 1000,
  fill = true,
  className,
}: SparklineProps) {
  const reactId = useId();
  const gradId = `sparkGrad-${reactId}`;
  const reduce = useReducedMotion();
  const pathRef = useDrawOn({ delay, duration });

  if (data.length === 0) return null;

  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const step = data.length > 1 ? width / (data.length - 1) : 0;
  const points = data.map(
    (v, i) => [i * step, height - ((v - min) / range) * height] as const,
  );
  const linePath = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`)
    .join(' ');
  const areaPath = `${linePath} L${width} ${height} L0 ${height} Z`;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      style={{ overflow: 'visible' }}
      aria-hidden
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.2" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {fill && (
        <path
          d={areaPath}
          fill={`url(#${gradId})`}
          style={{
            opacity: reduce ? 1 : 0,
            animation: reduce
              ? undefined
              : `k-fade-in 500ms ${delay + 400}ms forwards`,
          }}
        />
      )}
      <path
        ref={pathRef}
        d={linePath}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
