'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button, Icon } from '@/components/ui';
import { deleteGroupClient } from '@/lib/groups-client';
import { GroupFormDialog } from './GroupFormDialog';
import { GroupMembersBulkAddDialog } from './GroupMembersBulkAddDialog';
import type { Group } from '@/types/group';

export type GroupDetailAdminShellProps = {
  group: Group;
  canManage: boolean;
};

/**
 * S10 그룹 상세 상단 액션 shell — 편집/번호로 추가/삭제.
 *
 * 기존 members 개별 제거는 GroupMembersTable 의 행 단위 버튼으로 제공 (별도
 * 컴포넌트 확장 여지). 현재 수준에선 그룹 단위 액션만 노출.
 */
export function GroupDetailAdminShell({
  group,
  canManage,
}: GroupDetailAdminShellProps) {
  const router = useRouter();
  const [editOpen, setEditOpen] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!canManage) return null;

  const onDelete = async () => {
    if (!confirm(`그룹 "${group.name}" 을(를) 삭제하시겠습니까?\n멤버십은 모두 제거되지만 연락처 자체는 유지됩니다.`)) {
      return;
    }
    setDeleting(true);
    setErr(null);
    try {
      await deleteGroupClient(group.id);
      router.push('/groups');
      router.refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : '삭제 실패');
      setDeleting(false);
    }
  };

  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="flex items-center gap-2">
        <Button
          variant="secondary"
          size="sm"
          icon={<Icon name="plus" size={12} />}
          onClick={() => setBulkOpen(true)}
          disabled={deleting}
        >
          번호로 멤버 추가
        </Button>
        <Button
          variant="ghost"
          size="sm"
          icon={<Icon name="edit" size={12} />}
          onClick={() => setEditOpen(true)}
          disabled={deleting}
        >
          편집
        </Button>
        <Button
          variant="danger"
          size="sm"
          icon={<Icon name="trash" size={12} />}
          onClick={onDelete}
          loading={deleting}
        >
          삭제
        </Button>
      </div>
      {err ? (
        <span className="text-[11px] text-danger" role="alert">
          {err}
        </span>
      ) : null}
      <GroupFormDialog open={editOpen} onOpenChange={setEditOpen} group={group} />
      <GroupMembersBulkAddDialog
        open={bulkOpen}
        onOpenChange={setBulkOpen}
        groupId={group.id}
      />
    </div>
  );
}
