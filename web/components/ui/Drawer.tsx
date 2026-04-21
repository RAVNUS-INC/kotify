'use client';

import * as Dialog from '@radix-ui/react-dialog';
import { useId, type ReactNode } from 'react';
import { Icon } from './Icon';
import { cn } from '@/lib/cn';

export type DrawerWidth = 320 | 400 | 560;

export type DrawerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  width?: DrawerWidth;
  title?: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
};

export function Drawer({
  open,
  onOpenChange,
  width = 400,
  title,
  description,
  children,
  footer,
  className,
}: DrawerProps) {
  // useId로 unique ID 생성 — 같은 페이지에 여러 Drawer가 있어도 ID 충돌 없음
  const descId = useId();
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="k-drawer-overlay fixed inset-0 z-[1040] bg-black/30" />
        <Dialog.Content
          className={cn(
            'k-drawer-content fixed right-0 top-0 z-[1040] flex h-full flex-col',
            'border-l border-line bg-surface shadow-lg focus:outline-none',
            className,
          )}
          style={{ width }}
          aria-describedby={description ? descId : undefined}
        >
          {(title || description) && (
            <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
              <div className="min-w-0 flex-1">
                {title && (
                  <Dialog.Title className="m-0 text-base font-semibold tracking-tight text-ink">
                    {title}
                  </Dialog.Title>
                )}
                {description && (
                  <Dialog.Description
                    id={descId}
                    className="mt-0.5 text-sm text-ink-muted"
                  >
                    {description}
                  </Dialog.Description>
                )}
              </div>
              <Dialog.Close asChild>
                <button
                  type="button"
                  className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-ink-muted transition-colors duration-fast ease-out hover:bg-gray-2 hover:text-ink focus-visible:outline-none focus-visible:shadow-[0_0_0_3px_rgba(59,0,139,0.12)]"
                  aria-label="닫기"
                >
                  <Icon name="x" size={14} />
                </button>
              </Dialog.Close>
            </header>
          )}

          <div className="flex-1 overflow-y-auto">{children}</div>

          {footer && (
            <footer className="border-t border-line bg-surface px-5 py-3">
              {footer}
            </footer>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
