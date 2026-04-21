'use client';

import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

export type SegmentedItem<T extends string = string> = {
  value: T;
  label: ReactNode;
};

export type SegmentedProps<T extends string = string> = {
  items: ReadonlyArray<SegmentedItem<T>>;
  value: T;
  onChange: (value: T) => void;
  size?: 'sm' | 'md';
  'aria-label'?: string;
  className?: string;
};

export function Segmented<T extends string = string>({
  items,
  value,
  onChange,
  size = 'md',
  'aria-label': ariaLabel,
  className,
}: SegmentedProps<T>) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn('k-segctrl', size === 'sm' && 'text-xs', className)}
    >
      {items.map((item) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(item.value)}
            className={cn(active && 'on')}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
