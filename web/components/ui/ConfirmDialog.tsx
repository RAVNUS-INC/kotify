'use client';

import * as Dialog from '@radix-ui/react-dialog';
import { useCallback, useId, useRef, useState, type ReactNode } from 'react';

import { cn } from '@/lib/cn';
import { Button } from './Button';

export type ConfirmOptions = {
  /** 제목(헤딩). */
  title: ReactNode;
  /** 상세 설명. 줄바꿈(\n)은 그대로 표시된다. */
  description?: ReactNode;
  /** 확인 버튼 라벨. 미지정 시 tone 에 따라 '삭제'(danger)/'확인'(default). */
  confirmLabel?: string;
  /** 취소 버튼 라벨. 기본 '취소'. */
  cancelLabel?: string;
  /** danger 면 확인 버튼이 위험(빨강) 스타일. */
  tone?: 'default' | 'danger';
};

type ConfirmState = ConfirmOptions & { open: boolean };

export type UseConfirmResult = {
  /** 확인 다이얼로그를 띄우고 사용자 선택을 Promise<boolean> 로 반환. */
  confirm: (options: ConfirmOptions) => Promise<boolean>;
  /** 컴포넌트 JSX 에 렌더해야 하는 다이얼로그 엘리먼트. */
  dialog: ReactNode;
};

/**
 * window.confirm 을 대체하는 접근성 있는 확인 다이얼로그 훅.
 *
 * window.confirm 은 동기 블로킹이지만 이 훅은 Promise 기반이다 — 호출 시 새 Promise 를
 * 만들어 resolve 를 보관하고, 사용자가 확인/취소를 누르면 true/false 로 resolve 한다.
 * 전역 Provider 없이 컴포넌트별로 독립 동작한다(반환된 dialog 를 JSX 에 렌더).
 *
 * 사용:
 *   const { confirm, dialog } = useConfirm();
 *   const onDelete = async () => {
 *     if (!(await confirm({ title: '삭제', tone: 'danger' }))) return;
 *     ...
 *   };
 *   return (<>{dialog} ...</>);
 */
export function useConfirm(): UseConfirmResult {
  const [state, setState] = useState<ConfirmState | null>(null);
  const resolverRef = useRef<((ok: boolean) => void) | null>(null);

  const settle = useCallback((ok: boolean) => {
    const resolve = resolverRef.current;
    resolverRef.current = null;
    setState((prev) => (prev ? { ...prev, open: false } : prev));
    resolve?.(ok);
  }, []);

  const confirm = useCallback((options: ConfirmOptions) => {
    // 직전 confirm 이 미해결이면 false 로 정리(중첩 호출 방어).
    resolverRef.current?.(false);
    return new Promise<boolean>((resolve) => {
      resolverRef.current = resolve;
      setState({ ...options, open: true });
    });
  }, []);

  const dialog = state ? (
    <ConfirmDialog
      title={state.title}
      description={state.description}
      confirmLabel={state.confirmLabel}
      cancelLabel={state.cancelLabel}
      tone={state.tone}
      open={state.open}
      onConfirm={() => settle(true)}
      onCancel={() => settle(false)}
    />
  ) : null;

  return { confirm, dialog };
}

type ConfirmDialogProps = ConfirmOptions & {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

function ConfirmDialog({
  title,
  description,
  confirmLabel,
  cancelLabel = '취소',
  tone = 'default',
  open,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const descId = useId();
  const hasDescription = description != null && description !== '';
  const resolvedConfirmLabel = confirmLabel ?? (tone === 'danger' ? '삭제' : '확인');

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        // ESC·오버레이 클릭·X 등으로 닫히면 취소로 간주.
        if (!next) onCancel();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="k-confirm-overlay fixed inset-0 z-[1050] bg-black/30" />
        <Dialog.Content
          className={cn(
            'k-confirm-content fixed left-1/2 top-1/2 z-[1050] w-[min(92vw,400px)]',
            '-translate-x-1/2 -translate-y-1/2 rounded-lg border border-line bg-surface p-5',
            'shadow-lg focus:outline-none',
          )}
          aria-describedby={hasDescription ? descId : undefined}
        >
          <Dialog.Title className="m-0 text-base font-semibold tracking-tight text-ink">
            {title}
          </Dialog.Title>
          {hasDescription && (
            <Dialog.Description
              id={descId}
              className="mt-1.5 whitespace-pre-line text-sm text-ink-muted"
            >
              {description}
            </Dialog.Description>
          )}
          <div className="mt-5 flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onCancel}>
              {cancelLabel}
            </Button>
            <Button
              type="button"
              variant={tone === 'danger' ? 'danger' : 'primary'}
              onClick={onConfirm}
            >
              {resolvedConfirmLabel}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
