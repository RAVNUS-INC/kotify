'use client';

import { forwardRef, type ReactNode } from 'react';
import { Icon } from './Icon';
import { Input, type InputProps } from './Input';
import { Kbd } from './Kbd';
import { cn } from '@/lib/cn';

export type SearchInputProps = Omit<InputProps, 'type' | 'prefix' | 'suffix'> & {
  kbd?: ReactNode;
  onClear?: () => void;
};

export const SearchInput = forwardRef<HTMLInputElement, SearchInputProps>(function SearchInput(
  { kbd, onClear, value, className, ...rest },
  ref,
) {
  const hasValue = typeof value === 'string' && value.length > 0;
  const suffix = hasValue && onClear ? (
    <button
      type="button"
      aria-label="지우기"
      onClick={onClear}
      className="inline-flex h-full items-center justify-center px-1 text-ink-dim hover:text-ink"
    >
      <Icon name="x" size={12} />
    </button>
  ) : kbd ? (
    <Kbd className="mx-1 my-1">{kbd}</Kbd>
  ) : undefined;

  return (
    <Input
      ref={ref}
      type="search"
      value={value}
      prefix={<Icon name="search" size={14} />}
      suffix={suffix}
      className={cn(className)}
      {...rest}
    />
  );
});
