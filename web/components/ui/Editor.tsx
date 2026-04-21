'use client';

import {
  forwardRef,
  type ButtonHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from 'react';
import { cn } from '@/lib/cn';

export type EditorProps = TextareaHTMLAttributes<HTMLTextAreaElement> & {
  toolbar?: ReactNode;
  footer?: ReactNode;
  invalid?: boolean;
};

export const Editor = forwardRef<HTMLTextAreaElement, EditorProps>(
  function Editor(
    { toolbar, footer, invalid, className, rows = 5, ...rest },
    ref,
  ) {
    return (
      <div className={cn('k-editor', invalid && 'is-err', className)}>
        {toolbar && <div className="k-editor-tb">{toolbar}</div>}
        <textarea
          ref={ref}
          rows={rows}
          className="k-editor-body"
          aria-invalid={invalid || undefined}
          {...rest}
        />
        {footer && <div className="k-editor-ft">{footer}</div>}
      </div>
    );
  },
);

export type EditorToolbarButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  icon?: ReactNode;
};

export function EditorToolbarButton({
  icon,
  children,
  className,
  type = 'button',
  ...rest
}: EditorToolbarButtonProps) {
  return (
    <button type={type} className={cn('k-editor-tb-btn', className)} {...rest}>
      {icon}
      {children}
    </button>
  );
}

export function EditorToolbarDivider() {
  return <span className="k-editor-tb-btn divider" aria-hidden />;
}
