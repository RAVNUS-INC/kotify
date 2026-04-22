'use client';

import { useEffect, useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { Button, Drawer, Field, Icon, Input, Textarea } from '@/components/ui';
import {
  createGroupClient,
  updateGroupClient,
  type GroupInput,
} from '@/lib/groups-client';
import type { Group } from '@/types/group';

export type GroupFormDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 없으면 create, 있으면 edit. */
  group?: Group;
};

export function GroupFormDialog({
  open,
  onOpenChange,
  group,
}: GroupFormDialogProps) {
  const router = useRouter();
  const mode: 'create' | 'edit' = group ? 'edit' : 'create';

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName(group?.name ?? '');
    setDescription(group?.description ?? '');
    setError(null);
    setSubmitting(false);
  }, [open, group]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    if (!name.trim()) {
      setError('이름을 입력하세요');
      return;
    }
    setSubmitting(true);
    setError(null);

    const input: GroupInput = {
      name: name.trim(),
      description: description.trim() || null,
    };
    try {
      if (mode === 'edit' && group) {
        await updateGroupClient(group.id, input);
      } else {
        await createGroupClient(input);
      }
      onOpenChange(false);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : '저장 실패');
      setSubmitting(false);
    }
  };

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      width={400}
      title={mode === 'edit' ? '그룹 수정' : '새 그룹'}
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button
            variant="ghost"
            size="md"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            취소
          </Button>
          <Button
            variant="primary"
            size="md"
            type="submit"
            form="group-form"
            loading={submitting}
            icon={<Icon name="check" size={12} />}
          >
            {mode === 'edit' ? '저장' : '등록'}
          </Button>
        </div>
      }
    >
      <form id="group-form" onSubmit={onSubmit} className="space-y-4">
        <Field label="그룹명" required hint="같은 이름은 쓸 수 없습니다.">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
            disabled={submitting}
            required
          />
        </Field>
        <Field label="설명">
          <Textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            disabled={submitting}
            placeholder="예) 영업팀 전체 대상 공지 그룹"
          />
        </Field>
        {error ? (
          <div
            className="rounded border border-danger/30 bg-danger/5 p-2 text-sm text-danger"
            role="alert"
          >
            {error}
          </div>
        ) : null}
      </form>
    </Drawer>
  );
}
