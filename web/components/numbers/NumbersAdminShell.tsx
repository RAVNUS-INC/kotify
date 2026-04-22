'use client';

import { useState } from 'react';
import { Button, Icon } from '@/components/ui';
import { NumbersTable } from './NumbersTable';
import { RegisterNumberDialog } from './RegisterNumberDialog';
import type { SenderNumber } from '@/types/number';

export type NumbersAdminShellProps = {
  numbers: ReadonlyArray<SenderNumber>;
  canManage: boolean;
};

/**
 * admin 관리 UI 를 감싸는 client shell. 서버 컴포넌트(page.tsx)가 조회 데이터를
 * 주입하고, 이 shell 이 "번호 등록" dialog + 행 액션 상태를 관리한다.
 *
 * - canManage=false (viewer/sender) 이면 등록 버튼/액션 숨김.
 */
export function NumbersAdminShell({ numbers, canManage }: NumbersAdminShellProps) {
  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <>
      {canManage ? (
        <div className="mb-3 flex justify-end">
          <Button
            variant="primary"
            size="sm"
            icon={<Icon name="plus" size={12} />}
            onClick={() => setDialogOpen(true)}
          >
            번호 등록
          </Button>
        </div>
      ) : null}

      <NumbersTable numbers={numbers} canManage={canManage} />

      {canManage ? (
        <RegisterNumberDialog open={dialogOpen} onOpenChange={setDialogOpen} />
      ) : null}
    </>
  );
}
