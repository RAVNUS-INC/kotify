'use client';

import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

export type ToggleProps = {
  checked?: boolean;
  onChange?: (checked: boolean) => void;
  label?: ReactNode;
  sub?: ReactNode;
  disabled?: boolean;
  id?: string;
  name?: string;
  className?: string;
};

export function Toggle({
  checked = false,
  onChange,
  label,
  sub,
  disabled = false,
  id,
  name,
  className,
}: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      id={id}
      name={name}
      aria-checked={checked}
      aria-disabled={disabled || undefined}
      disabled={disabled}
      onClick={() => {
        if (!disabled) onChange?.(!checked);
      }}
      className={cn(
        'k-toggle',
        checked && 'on',
        disabled && 'opacity-50 cursor-not-allowed',
        className,
      )}
    >
      <span className="track" aria-hidden />
      {label && (
        <span className="flex flex-col items-start">
          <span>{label}</span>
          {sub && <span className="k-toggle-label-sub">{sub}</span>}
        </span>
      )}
    </button>
  );
}
