import type { HTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

export function Kbd({ className, children, ...rest }: HTMLAttributes<HTMLElement>) {
  return (
    <kbd
      className={cn(
        'inline-flex items-center rounded-xs border border-line bg-surface-subtle px-1.5 py-0.5 ' +
          'font-sans text-[11px] font-semibold text-ink-dim leading-none',
        className,
      )}
      {...rest}
    >
      {children}
    </kbd>
  );
}
