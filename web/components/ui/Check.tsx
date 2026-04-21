'use client';

import {
  forwardRef,
  useEffect,
  useRef,
  type InputHTMLAttributes,
  type ReactNode,
} from 'react';
import { cn } from '@/lib/cn';

export type CheckProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'size'> & {
  checked?: boolean;
  partial?: boolean;
  label?: ReactNode;
  sub?: ReactNode;
  size?: 'sm' | 'md';
  onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
};

export const Check = forwardRef<HTMLInputElement, CheckProps>(function Check(
  {
    checked = false,
    partial = false,
    label,
    sub,
    size = 'md',
    disabled,
    className,
    onChange,
    ...rest
  },
  forwardedRef,
) {
  const innerRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (innerRef.current) innerRef.current.indeterminate = partial;
  }, [partial]);

  const setRef = (el: HTMLInputElement | null) => {
    innerRef.current = el;
    if (typeof forwardedRef === 'function') forwardedRef(el);
    else if (forwardedRef) forwardedRef.current = el;
  };

  return (
    <label
      className={cn(
        'k-check',
        checked && 'on',
        partial && 'partial',
        disabled && 'disabled',
        className,
      )}
      style={size === 'sm' ? { fontSize: 12 } : undefined}
    >
      <input
        ref={setRef}
        type="checkbox"
        className="sr-only"
        checked={checked}
        disabled={disabled}
        onChange={onChange}
        {...rest}
      />
      <span
        className="box"
        aria-hidden
        style={size === 'sm' ? { width: 14, height: 14 } : undefined}
      />
      {label && (
        <span className="flex flex-col">
          <span>{label}</span>
          {sub && <span className="text-[11px] text-ink-muted">{sub}</span>}
        </span>
      )}
    </label>
  );
});
