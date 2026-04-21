'use client';

import { useRef, type KeyboardEvent, type ReactNode } from 'react';
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
  'aria-label': ariaLabel = '탭 선택',
  className,
}: SegmentedProps<T>) {
  const listRef = useRef<HTMLDivElement>(null);

  const focusAt = (index: number) => {
    const btns = listRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    btns?.[index]?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const last = items.length - 1;
    let next = index;
    switch (e.key) {
      case 'ArrowRight':
        next = index === last ? 0 : index + 1;
        break;
      case 'ArrowLeft':
        next = index === 0 ? last : index - 1;
        break;
      case 'Home':
        next = 0;
        break;
      case 'End':
        next = last;
        break;
      default:
        return;
    }
    e.preventDefault();
    const target = items[next];
    if (target) {
      onChange(target.value);
      focusAt(next);
    }
  };

  return (
    <div
      ref={listRef}
      role="tablist"
      aria-label={ariaLabel}
      className={cn('k-segctrl', size === 'sm' && 'text-xs', className)}
    >
      {items.map((item, i) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(item.value)}
            onKeyDown={(e) => onKeyDown(e, i)}
            className={cn(active && 'on')}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
