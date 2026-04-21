'use client';

import {
  forwardRef,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from 'react';
import { cn } from '@/lib/cn';

export type ChipFieldProps = {
  value: ReadonlyArray<string>;
  onChange: (next: string[]) => void;
  placeholder?: string;
  id?: string;
  name?: string;
  disabled?: boolean;
  invalid?: boolean;
  maxChips?: number;
  className?: string;
  'aria-label'?: string;
  /** 칩 우측에 카운트/뱃지 등 표시용 */
  renderChipExtra?: (chip: string, index: number) => ReactNode;
};

export const ChipField = forwardRef<HTMLInputElement, ChipFieldProps>(
  function ChipField(
    {
      value,
      onChange,
      placeholder,
      id,
      name,
      disabled,
      invalid,
      maxChips,
      className,
      'aria-label': ariaLabel,
      renderChipExtra,
    },
    forwardedRef,
  ) {
    const [input, setInput] = useState('');
    const innerRef = useRef<HTMLInputElement | null>(null);
    const rootRef = useRef<HTMLDivElement>(null);

    const setRef = (el: HTMLInputElement | null) => {
      innerRef.current = el;
      if (typeof forwardedRef === 'function') forwardedRef(el);
      else if (forwardedRef) forwardedRef.current = el;
    };

    const addChip = (raw: string) => {
      const trimmed = raw.trim().replace(/,$/, '').trim();
      if (!trimmed) return;
      if (value.includes(trimmed)) return;
      if (maxChips !== undefined && value.length >= maxChips) return;
      onChange([...value, trimmed]);
    };

    const removeChip = (index: number) => {
      onChange(value.filter((_, i) => i !== index));
    };

    const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
      if (
        (e.key === 'Enter' || e.key === ',') &&
        !e.nativeEvent.isComposing
      ) {
        if (input.trim()) {
          e.preventDefault();
          addChip(input);
          setInput('');
        }
      } else if (e.key === 'Backspace' && !input && value.length > 0) {
        removeChip(value.length - 1);
      }
    };

    const onBlur = () => {
      if (input.trim()) {
        addChip(input);
        setInput('');
      }
    };

    const onRootClick = (e: React.MouseEvent) => {
      if (e.target === rootRef.current) innerRef.current?.focus();
    };

    return (
      <div
        ref={rootRef}
        role="group"
        aria-label={ariaLabel}
        aria-disabled={disabled || undefined}
        onClick={onRootClick}
        className={cn(
          'k-chipfield',
          invalid && 'is-err',
          disabled && 'opacity-60 pointer-events-none',
          className,
        )}
      >
        {value.map((chip, i) => (
          <span key={`${chip}-${i}`} className="k-chip">
            <span>{chip}</span>
            {renderChipExtra?.(chip, i)}
            <button
              type="button"
              className="x"
              aria-label={`${chip} 제거`}
              onClick={() => removeChip(i)}
              tabIndex={-1}
            >
              ×
            </button>
          </span>
        ))}
        <input
          ref={setRef}
          id={id}
          name={name}
          className="k-chipfield-input"
          value={input}
          disabled={disabled}
          placeholder={value.length === 0 ? placeholder : undefined}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={onBlur}
          aria-autocomplete="list"
          aria-invalid={invalid || undefined}
        />
      </div>
    );
  },
);
