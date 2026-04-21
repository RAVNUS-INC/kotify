import type { CSSProperties } from 'react';
import { cn } from '@/lib/cn';

export type SkeletonProps = {
  width?: number | string;
  height?: number | string;
  radius?: number;
  className?: string;
  style?: CSSProperties;
};

export function Skeleton({
  width = '100%',
  height = 14,
  radius = 4,
  className,
  style,
}: SkeletonProps) {
  return (
    <div
      aria-busy
      role="status"
      aria-label="로딩 중"
      className={cn(className)}
      style={{
        width,
        height,
        borderRadius: radius,
        background:
          'linear-gradient(90deg, var(--gray-2) 0%, var(--gray-3) 50%, var(--gray-2) 100%)',
        backgroundSize: '200% 100%',
        animation: 'k-skel 1.4s ease-in-out infinite',
        ...style,
      }}
    />
  );
}

export type SkeletonTextProps = {
  lines?: number;
  widths?: ReadonlyArray<string | number>;
  gap?: number;
  className?: string;
};

export function SkeletonText({
  lines = 3,
  widths = ['100%', '92%', '70%'],
  gap = 8,
  className,
}: SkeletonTextProps) {
  return (
    <div className={cn('flex flex-col', className)} style={{ gap }}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} width={widths[i % widths.length]} height={12} />
      ))}
    </div>
  );
}
