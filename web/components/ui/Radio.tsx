'use client';

import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react';
import { cn } from '@/lib/cn';

export type RadioProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & {
  checked?: boolean;
  label?: ReactNode;
  sub?: ReactNode;
  onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
};

export const Radio = forwardRef<HTMLInputElement, RadioProps>(function Radio(
  { checked = false, label, sub, disabled, className, onChange, ...rest },
  ref,
) {
  return (
    <label
      className={cn('k-radio', checked && 'on', disabled && 'disabled', className)}
    >
      <input
        ref={ref}
        type="radio"
        className="sr-only"
        checked={checked}
        disabled={disabled}
        onChange={onChange}
        {...rest}
      />
      <span className="box" aria-hidden />
      {label && (
        <span className="flex flex-col">
          <span>{label}</span>
          {sub && <span className="mt-0.5 text-[11px] text-ink-muted">{sub}</span>}
        </span>
      )}
    </label>
  );
});
