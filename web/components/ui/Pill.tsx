import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';

export type PillTone = 'neutral' | 'brand' | 'success' | 'warning' | 'danger';

export type PillProps = HTMLAttributes<HTMLSpanElement> & {
  tone?: PillTone;
  icon?: ReactNode;
};

const base =
  'inline-flex items-center gap-1 h-[18px] px-1.5 rounded-full ' +
  'text-[11px] leading-none font-medium';

const tones: Record<PillTone, string> = {
  neutral: 'bg-gray-2 text-gray-9',
  brand: 'bg-brand-soft text-brand',
  success: 'bg-success-bg text-success',
  warning: 'bg-warning-bg text-warning',
  danger: 'bg-danger-bg text-danger',
};

export function Pill({ tone = 'neutral', icon, className, children, ...rest }: PillProps) {
  return (
    <span className={cn(base, tones[tone], className)} {...rest}>
      {icon && <span className="inline-flex shrink-0">{icon}</span>}
      {children}
    </span>
  );
}
