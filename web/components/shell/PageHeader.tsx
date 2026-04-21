import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';

export type PageHeaderProps = HTMLAttributes<HTMLDivElement> & {
  title: ReactNode;
  sub?: ReactNode;
  actions?: ReactNode;
};

export function PageHeader({
  title,
  sub,
  actions,
  className,
  ...rest
}: PageHeaderProps) {
  return (
    <div className={cn('k-page-head', className)} {...rest}>
      <div className="min-w-0">
        <h1 className="k-page-title">{title}</h1>
        {sub && <p className="k-page-sub">{sub}</p>}
      </div>
      {actions && (
        <div className="flex shrink-0 items-center gap-2">{actions}</div>
      )}
    </div>
  );
}
