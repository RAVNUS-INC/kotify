import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';

export type CardProps = HTMLAttributes<HTMLDivElement>;

export function Card({ className, children, ...rest }: CardProps) {
  return (
    <div
      className={cn('rounded-lg border border-line bg-surface', className)}
      {...rest}
    >
      {children}
    </div>
  );
}

export type CardHeaderProps = Omit<HTMLAttributes<HTMLDivElement>, 'title'> & {
  title?: ReactNode;
  subtitle?: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
};

export function CardHeader({
  title,
  subtitle,
  eyebrow,
  actions,
  className,
  children,
  ...rest
}: CardHeaderProps) {
  return (
    <div
      className={cn(
        'flex items-center justify-between gap-3 border-b border-line px-5 py-3.5',
        className,
      )}
      {...rest}
    >
      <div className="min-w-0">
        {eyebrow && (
          <div className="mb-0.5 font-mono text-[10.5px] uppercase tracking-[0.08em] text-ink-dim">
            {eyebrow}
          </div>
        )}
        {title && (
          <h3 className="m-0 text-[13.5px] font-semibold tracking-[-0.01em] text-ink">
            {title}
          </h3>
        )}
        {subtitle && <p className="mt-0.5 text-sm text-ink-muted">{subtitle}</p>}
        {children}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

export type CardBodyProps = HTMLAttributes<HTMLDivElement> & {
  padded?: boolean;
};

export function CardBody({ padded = true, className, children, ...rest }: CardBodyProps) {
  return (
    <div className={cn(padded && 'px-5 py-4', className)} {...rest}>
      {children}
    </div>
  );
}

export type CardFooterProps = HTMLAttributes<HTMLDivElement> & {
  align?: 'left' | 'right' | 'between';
};

const alignMap: Record<NonNullable<CardFooterProps['align']>, string> = {
  left: 'justify-start',
  right: 'justify-end',
  between: 'justify-between',
};

export function CardFooter({
  align = 'right',
  className,
  children,
  ...rest
}: CardFooterProps) {
  return (
    <div
      className={cn(
        'flex items-center gap-2 border-t border-line px-5 py-3',
        alignMap[align],
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}
