'use client';

import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react';
import { cn } from '@/lib/cn';

export type InputSize = 'sm' | 'md' | 'lg';

export type InputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'size' | 'prefix'> & {
  prefix?: ReactNode;
  suffix?: ReactNode;
  invalid?: boolean;
  valid?: boolean;
  inputSize?: InputSize;
  mono?: boolean;
};

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  {
    prefix,
    suffix,
    invalid,
    valid,
    inputSize = 'md',
    mono,
    className,
    type = 'text',
    ...rest
  },
  ref,
) {
  const sizeClass = inputSize === 'md' ? '' : inputSize;
  const stateClass = invalid ? 'is-err' : valid ? 'is-ok' : '';

  if (prefix || suffix) {
    return (
      <div className={cn('k-inputgroup', sizeClass, stateClass, className)}>
        {prefix && <span className="k-prefix">{prefix}</span>}
        <input
          ref={ref}
          type={type}
          className={cn('k-input', mono && 'mono')}
          aria-invalid={invalid || undefined}
          {...rest}
        />
        {suffix && <span className="k-suffix">{suffix}</span>}
      </div>
    );
  }

  return (
    <input
      ref={ref}
      type={type}
      className={cn('k-input', sizeClass, mono && 'mono', stateClass, className)}
      aria-invalid={invalid || undefined}
      {...rest}
    />
  );
});
