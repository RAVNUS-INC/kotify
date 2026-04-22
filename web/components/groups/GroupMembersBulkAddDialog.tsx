'use client';

import { useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import {
  Button,
  Check,
  Drawer,
  Field,
  Icon,
  Textarea,
} from '@/components/ui';
import {
  bulkAddGroupMembersClient,
  type BulkAddResult,
} from '@/lib/groups-client';

export type GroupMembersBulkAddDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  groupId: string;
};

/**
 * 전화번호를 한 줄에 하나씩 붙여넣기 → bulk-add.
 * autoCreate 체크박스로 "없는 연락처는 자동 생성" 옵션.
 */
export function GroupMembersBulkAddDialog({
  open,
  onOpenChange,
  groupId,
}: GroupMembersBulkAddDialogProps) {
  const router = useRouter();
  const [text, setText] = useState('');
  const [autoCreate, setAutoCreate] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<BulkAddResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setText('');
    setAutoCreate(true);
    setSubmitting(false);
    setResult(null);
    setError(null);
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    // 한 줄에 하나 또는 쉼표/세미콜론 구분자 허용.
    const phones = text
      .split(/[\n,;]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (phones.length === 0) {
      setError('전화번호를 한 줄에 하나씩 입력하세요');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const r = await bulkAddGroupMembersClient(groupId, phones, { autoCreate });
      setResult(r);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : '추가 실패');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Drawer
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
      width={400}
      title="전화번호로 멤버 추가"
      description="한 줄에 하나씩 붙여넣으세요. 쉼표/세미콜론 구분도 허용됩니다."
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button
            variant="ghost"
            size="md"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            {result ? '닫기' : '취소'}
          </Button>
          {!result ? (
            <Button
              variant="primary"
              size="md"
              type="submit"
              form="group-bulk-add-form"
              loading={submitting}
              icon={<Icon name="plus" size={12} />}
            >
              추가
            </Button>
          ) : null}
        </div>
      }
    >
      {!result ? (
        <form
          id="group-bulk-add-form"
          onSubmit={onSubmit}
          className="space-y-4"
        >
          <Field label="전화번호 목록">
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={10}
              placeholder="010-1111-2222&#10;010-3333-4444&#10;010-5555-6666"
              disabled={submitting}
            />
          </Field>
          <Check
            checked={autoCreate}
            onChange={(e) => setAutoCreate(e.target.checked)}
            disabled={submitting}
            label="없는 연락처는 자동 생성"
            sub="체크를 해제하면 기존 주소록에 없는 번호는 건너뜀."
          />
          {error ? (
            <div
              className="rounded border border-danger/30 bg-danger/5 p-2 text-sm text-danger"
              role="alert"
            >
              {error}
            </div>
          ) : null}
        </form>
      ) : (
        <div className="space-y-3">
          <div className="rounded-lg border border-line bg-gray-1 p-4">
            <h3 className="mb-2 text-sm font-semibold text-ink">처리 결과</h3>
            <ul className="space-y-1 text-sm text-ink-muted">
              <li>요청 번호: <strong>{result.requested}</strong></li>
              <li>기존 연락처 추가:{' '}
                <strong className="text-brand">{result.added_existing}</strong>
              </li>
              <li>새로 생성 후 추가:{' '}
                <strong className="text-ok">{result.created_new}</strong>
              </li>
              <li>이미 멤버였음:{' '}
                <strong>{result.skipped_existing_member}</strong>
              </li>
              <li>연락처 없음(건너뜀):{' '}
                <strong className="text-warning">
                  {result.skipped_no_contact}
                </strong>
              </li>
            </ul>
          </div>
          <Button variant="secondary" size="md" onClick={reset} full>
            추가 입력
          </Button>
        </div>
      )}
    </Drawer>
  );
}
