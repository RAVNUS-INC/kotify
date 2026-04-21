import type { HTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

export function Kbd({ className, children, ...rest }: HTMLAttributes<HTMLElement>) {
  return (
    <kbd
      className={cn(
        'inline-flex items-center rounded-xs border border-line bg-gray-1 px-1.5 py-0.5 ' +
          'font-mono text-xs text-ink-dim leading-none',
        className,
      )}
      {...rest}
    >
      {children}
    </kbd>
  );
}
