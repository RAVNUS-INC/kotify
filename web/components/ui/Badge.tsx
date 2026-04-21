import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';

export type BadgeKind =
  | 'neutral'
  | 'success'
  | 'warning'
  | 'danger'
  | 'info'
  | 'brand';

export type BadgeProps = HTMLAttributes<HTMLSpanElement> & {
  kind?: BadgeKind;
  icon?: ReactNode;
  dot?: boolean;
};

const base =
  'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 ' +
  'font-mono text-xs font-medium leading-[16px]';

const kinds: Record<BadgeKind, string> = {
  neutral: 'border-line bg-gray-1 text-gray-8',
  success: 'border-success/25 bg-success-bg text-success',
  warning: 'border-warning/25 bg-warning-bg text-warning',
  danger: 'border-danger/25 bg-danger-bg text-danger',
  info: 'border-info/25 bg-info-bg text-info',
  brand: 'border-brand-border bg-brand-soft text-brand',
};

export function Badge({
  kind = 'neutral',
  icon,
  dot = false,
  className,
  children,
  ...rest
}: BadgeProps) {
  return (
    <span className={cn(base, kinds[kind], className)} {...rest}>
      {dot && (
        <span
          aria-hidden
          className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-current"
        />
      )}
      {icon && <span className="inline-flex shrink-0">{icon}</span>}
      {children}
    </span>
  );
}
