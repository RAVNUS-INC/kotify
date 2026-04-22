'use client';

import { useState } from 'react';
import { Button, Icon } from '@/components/ui';
import { GroupFormDialog } from './GroupFormDialog';

export type GroupsAdminShellProps = {
  canManage: boolean;
};

/**
 * S9 그룹 목록 상단 "새 그룹" 버튼 + 생성 Drawer 를 묶는 client shell.
 */
export function GroupsAdminShell({ canManage }: GroupsAdminShellProps) {
  const [open, setOpen] = useState(false);
  if (!canManage) return null;
  return (
    <>
      <Button
        variant="primary"
        size="sm"
        icon={<Icon name="plus" size={12} />}
        onClick={() => setOpen(true)}
      >
        새 그룹
      </Button>
      <GroupFormDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
