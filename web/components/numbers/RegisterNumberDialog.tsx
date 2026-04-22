'use client';

import { useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { Button, Check, Drawer, Field, Icon, Input } from '@/components/ui';
import { createNumberClient } from '@/lib/numbers-client';

export type RegisterNumberDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

/**
 * 새 발신번호 등록 Drawer. 서버에서 `409 duplicate_number` 를 돌려주면 number
 * 필드 옆에 inline 에러 표시.
 */
export function RegisterNumberDialog({
  open,
  onOpenChange,
}: RegisterNumberDialogProps) {
  const router = useRouter();
  const [number, setNumber] = useState('');
  const [label, setLabel] = useState('');
  const [rcsEnabled, setRcsEnabled] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setNumber('');
    setLabel('');
    setRcsEnabled(false);
    setError(null);
    setSubmitting(false);
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    const digits = number.replace(/\D/g, '');
    if (!digits) {
      setError('숫자를 포함한 번호를 입력하세요');
      return;
    }
    if (!label.trim()) {
      setError('브랜드/라벨을 입력하세요');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await createNumberClient({ number: digits, label: label.trim(), rcsEnabled });
      reset();
      onOpenChange(false);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : '등록 실패');
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
      title="발신번호 등록"
      description="msghub 에 등록된 번호를 추가합니다. RCS 사용 번호는 별도 승인 절차가 필요합니다."
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
            form="register-number-form"
            loading={submitting}
            icon={<Icon name="plus" size={12} />}
          >
            등록
          </Button>
        </div>
      }
    >
      <form id="register-number-form" onSubmit={onSubmit} className="space-y-4">
        <Field label="번호" hint="하이픈/공백 허용 — 숫자만 저장됩니다.">
          <Input
            value={number}
            onChange={(e) => setNumber(e.target.value)}
            placeholder="070-1234-5678"
            autoFocus
            disabled={submitting}
            required
          />
        </Field>
        <Field label="브랜드/라벨">
          <Input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="예) 영업팀"
            disabled={submitting}
            required
          />
        </Field>
        <Check
          checked={rcsEnabled}
          onChange={(e) => setRcsEnabled(e.target.checked)}
          disabled={submitting}
          label="RCS 사용 (별도 승인 필요)"
        />
        {error ? (
          <div className="rounded border border-danger/30 bg-danger/5 p-2 text-sm text-danger" role="alert">
            {error}
          </div>
        ) : null}
      </form>
    </Drawer>
  );
}
