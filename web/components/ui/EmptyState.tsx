import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { Icon, type IconName } from './Icon';

export type EmptyStateSize = 'sm' | 'md' | 'lg';

export type EmptyStateProps = {
  icon?: IconName;
  title?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  size?: EmptyStateSize;
  className?: string;
};

const iconSizes: Record<EmptyStateSize, number> = { sm: 22, md: 28, lg: 36 };
const pads: Record<EmptyStateSize, string> = {
  sm: 'py-6 px-6',
  md: 'py-10 px-8',
  lg: 'py-16 px-10',
};

export function EmptyState({
  icon = 'inbox',
  title,
  description,
  action,
  size = 'md',
  className,
}: EmptyStateProps) {
  const iconSize = iconSizes[size];
  return (
    <div
      className={cn(
        'flex flex-col items-center gap-1.5 text-center',
        pads[size],
        className,
      )}
    >
      <div
        className="mb-1.5 flex items-center justify-center rounded-full bg-gray-1 text-gray-6"
        style={{ width: iconSize * 2, height: iconSize * 2 }}
      >
        <Icon name={icon} size={iconSize} />
      </div>
      {title && <div className="text-base font-semibold text-ink">{title}</div>}
      {description && (
        <div className="max-w-[320px] text-sm leading-relaxed text-ink-muted">
          {description}
        </div>
      )}
      {action && <div className="mt-2.5">{action}</div>}
    </div>
  );
}
