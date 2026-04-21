import { cn } from '@/lib/cn';

export type PulseDotProps = {
  color?: string;
  size?: number;
  className?: string;
  title?: string;
};

/**
 * 온라인/실시간 인디케이터. CSS `k-pulse-out` keyframe 사용 (tokens.css).
 * `prefers-reduced-motion: reduce` 시 globals.css 규칙으로 자동 정지.
 */
export function PulseDot({
  color = 'var(--brand)',
  size = 8,
  className,
  title,
}: PulseDotProps) {
  return (
    <span
      className={cn('relative inline-block', className)}
      style={{ width: size, height: size }}
      role={title ? 'img' : undefined}
      aria-label={title}
      aria-hidden={!title}
    >
      <span
        className="absolute inset-0 rounded-full"
        style={{
          background: color,
          opacity: 0.4,
          animation: 'k-pulse-out 1.4s ease-out infinite',
        }}
      />
      <span
        className="absolute inset-0 rounded-full"
        style={{ background: color }}
      />
    </span>
  );
}
