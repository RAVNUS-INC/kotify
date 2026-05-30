'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  deleteNumberClient,
  setDefaultNumberClient,
  toggleNumberClient,
} from '@/lib/numbers-client';
import type { SenderNumber } from '@/types/number';
import { Button, Icon, useConfirm } from '@/components/ui';

export type NumberActionsProps = {
  number: SenderNumber;
  /** admin 이 아닐 땐 액션 전체 숨김 */
  canManage: boolean;
};

/**
 * 발신번호 행 단위 액션 — 기본 지정 / 활성토글 / 삭제.
 *
 * - 기본 지정: 승인(활성) 상태에서만 노출
 * - 활성 토글: 항상 노출, 현재 상태 반전
 * - 삭제: 비활성(`expired`) 상태에서만 노출 (backend 가 422 반환)
 *
 * 확인 UX 는 Radix Dialog 기반 ConfirmDialog(useConfirm) 사용.
 */
export function NumberActions({ number, canManage }: NumberActionsProps) {
  const router = useRouter();
  const [busy, setBusy] = useState<'default' | 'toggle' | 'delete' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { confirm, dialog } = useConfirm();

  if (!canManage) return null;

  const isActive = number.status === 'approved';

  const run = async (
    kind: 'default' | 'toggle' | 'delete',
    fn: () => Promise<unknown>,
  ) => {
    setBusy(kind);
    setError(null);
    try {
      await fn();
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : '처리 실패');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex items-center justify-end gap-1">
      {dialog}
      {isActive ? (
        <Button
          variant="ghost"
          size="sm"
          disabled={busy !== null}
          onClick={() => run('default', () => setDefaultNumberClient(number.id))}
          title="기본 발신번호로 지정"
          icon={<Icon name="check" size={12} />}
        >
          기본
        </Button>
      ) : null}
      <Button
        variant="ghost"
        size="sm"
        disabled={busy !== null}
        onClick={() => run('toggle', () => toggleNumberClient(number.id))}
        title={isActive ? '비활성화' : '활성화'}
      >
        {isActive ? '비활성' : '활성'}
      </Button>
      {!isActive ? (
        <Button
          variant="danger"
          size="sm"
          disabled={busy !== null}
          onClick={async () => {
            if (
              !(await confirm({
                title: '발신번호 삭제',
                description: `'${number.number}' 발신번호를 삭제하시겠습니까?`,
                tone: 'danger',
                confirmLabel: '삭제',
              }))
            )
              return;
            void run('delete', () => deleteNumberClient(number.id));
          }}
          icon={<Icon name="trash" size={12} />}
        >
          삭제
        </Button>
      ) : null}
      {error ? (
        <span className="ml-2 text-[11px] text-danger" role="alert">
          {error}
        </span>
      ) : null}
    </div>
  );
}
