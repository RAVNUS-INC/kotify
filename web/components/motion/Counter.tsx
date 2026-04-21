'use client';

import type { HTMLAttributes } from 'react';
import { cn } from '@/lib/cn';
import { useCountUp } from './useCountUp';

export type CounterProps = Omit<HTMLAttributes<HTMLSpanElement>, 'children'> & {
  value: number;
  format?: (n: number) => string;
  duration?: number;
  delay?: number;
};

export function Counter({
  value,
  format,
  duration = 900,
  delay = 0,
  className,
  style,
  ...rest
}: CounterProps) {
  const n = useCountUp(value, { duration, delay });
  const out = format ? format(n) : n.toLocaleString('ko-KR');
  return (
    <span
      className={cn(className)}
      style={{ fontVariantNumeric: 'tabular-nums', ...style }}
      {...rest}
    >
      {out}
    </span>
  );
}
