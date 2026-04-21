'use client';

import type { HTMLAttributes } from 'react';
import { cn } from '@/lib/cn';
import { useCountUp } from './useCountUp';

export type CounterFormat =
  | 'number'
  | 'currency'
  | 'percent'
  | ((n: number) => string);

export type CounterProps = Omit<HTMLAttributes<HTMLSpanElement>, 'children'> & {
  value: number;
  format?: CounterFormat;
  duration?: number;
  delay?: number;
  /** percent 포맷에서 소수점 자리수 (기본 1) */
  fractionDigits?: number;
};

function applyFormat(
  n: number,
  format: CounterFormat | undefined,
  fractionDigits: number,
): string {
  if (typeof format === 'function') return format(n);
  switch (format) {
    case 'currency':
      return `₩${n.toLocaleString('ko-KR')}`;
    case 'percent':
      return `${n.toFixed(fractionDigits)}%`;
    case 'number':
    default:
      return n.toLocaleString('ko-KR');
  }
}

export function Counter({
  value,
  format,
  duration = 900,
  delay = 0,
  fractionDigits = 1,
  className,
  style,
  ...rest
}: CounterProps) {
  const n = useCountUp(value, { duration, delay });
  return (
    <span
      className={cn(className)}
      style={{ fontVariantNumeric: 'tabular-nums', ...style }}
      {...rest}
    >
      {applyFormat(n, format, fractionDigits)}
    </span>
  );
}
