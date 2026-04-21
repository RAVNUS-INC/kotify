import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';

export type FieldCounter = {
  value: ReactNode;
  state?: 'warn' | 'err';
};

export type FieldProps = Omit<HTMLAttributes<HTMLDivElement>, 'children'> & {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  ok?: ReactNode;
  required?: boolean;
  optional?: boolean;
  htmlFor?: string;
  counter?: FieldCounter;
  children: ReactNode;
};

export function Field({
  label,
  hint,
  error,
  ok,
  required,
  optional,
  htmlFor,
  counter,
  className,
  children,
  ...rest
}: FieldProps) {
  return (
    <div className={cn('k-field', className)} {...rest}>
      {(label || counter) && (
        <div className="k-field-row">
          {label && (
            <label htmlFor={htmlFor} className="k-label">
              {label}
              {required && (
                <>
                  <span className="req" aria-hidden>
                    *
                  </span>
                  <span className="sr-only">필수</span>
                </>
              )}
              {optional && <span className="opt">선택</span>}
            </label>
          )}
          {counter && (
            <div className={cn('k-counter', counter.state && counter.state)}>
              {counter.value}
            </div>
          )}
        </div>
      )}
      {children}
      {error && (
        <div className="k-err" role="alert">
          <span className="font-mono">✗</span> {error}
        </div>
      )}
      {ok && (
        <div className="k-ok">
          <span className="font-mono">✓</span> {ok}
        </div>
      )}
      {hint && !error && !ok && <div className="k-hint">{hint}</div>}
    </div>
  );
}
