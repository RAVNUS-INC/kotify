'use client';

import { useId, useRef, useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { Button, Field, Icon, Input, Segmented } from '@/components/ui';
import { sendFaxClient } from '@/lib/pbx-client';
import { FAX_STATUS_LABEL, isValidFaxNumber, MAX_FAX_PDF_BYTES } from '@/lib/pbx-format';
import type { FaxResolution } from '@/types/pbx';

const RESOLUTIONS: ReadonlyArray<{ value: FaxResolution; label: string }> = [
  { value: 'standard', label: '보통' },
  { value: 'medium', label: '선명' },
  { value: 'high', label: '고화질' },
];

/** 입력값 검사. 문제가 없으면 null. 서버가 같은 규칙으로 다시 검사한다. */
export function validateFaxInput(recipient: string, file: File | null): string | null {
  if (!isValidFaxNumber(recipient)) return '받는 팩스 번호를 확인하세요 (국내 번호, 숫자 9~11자리)';
  if (!file) return 'PDF 파일을 선택하세요';
  if (file.size === 0) return '빈 파일입니다';
  if (file.size > MAX_FAX_PDF_BYTES) return 'PDF 는 최대 10MB 까지 보낼 수 있습니다';
  const pdfType = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
  if (!pdfType) return 'PDF 파일만 보낼 수 있습니다';
  return null;
}

export function FaxComposer() {
  const router = useRouter();
  const fileId = useId();
  const fileRef = useRef<HTMLInputElement>(null);
  const [recipient, setRecipient] = useState('');
  const [resolution, setResolution] = useState<FaxResolution>('standard');
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    const problem = validateFaxInput(recipient, file);
    if (problem || !file) {
      setMsg({ kind: 'err', text: problem ?? 'PDF 파일을 선택하세요' });
      return;
    }
    setSubmitting(true);
    setMsg(null);
    try {
      const job = await sendFaxClient({ recipient, resolution, file });
      setMsg({
        kind: job.status === 'FAILED' ? 'err' : 'ok',
        text:
          job.status === 'FAILED'
            ? (job.error ?? '발송에 실패했습니다')
            : `${FAX_STATUS_LABEL[job.status]} — 결과는 아래 이력에서 확인하세요`,
      });
      if (job.status !== 'FAILED') {
        setRecipient('');
        setFile(null);
        if (fileRef.current) fileRef.current.value = '';
      }
      router.refresh();
    } catch (err) {
      setMsg({ kind: 'err', text: err instanceof Error ? err.message : '발송 실패' });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={onSubmit}
      aria-label="팩스 보내기"
      className="rounded-lg border border-line bg-surface p-5"
    >
      <div className="grid gap-4 md:grid-cols-[1fr_1fr_auto]">
        <Field label="받는 팩스 번호" required>
          <Input
            value={recipient}
            onChange={(e) => setRecipient(e.target.value)}
            placeholder="02-0000-0000"
            inputMode="tel"
            autoComplete="off"
            disabled={submitting}
          />
        </Field>
        <Field label="PDF 파일" required htmlFor={fileId} hint="최대 10MB">
          <input
            id={fileId}
            ref={fileRef}
            type="file"
            accept="application/pdf,.pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            disabled={submitting}
            className="block w-full text-sm text-ink-muted file:mr-3 file:rounded file:border file:border-gray-4 file:bg-surface file:px-2.5 file:py-1 file:text-sm file:text-ink"
          />
        </Field>
        <Field label="해상도">
          <Segmented
            aria-label="해상도"
            items={RESOLUTIONS}
            value={resolution}
            onChange={setResolution}
          />
        </Field>
      </div>
      <div className="mt-4 flex items-center justify-between gap-3">
        <p
          role={msg?.kind === 'err' ? 'alert' : 'status'}
          className={msg?.kind === 'err' ? 'text-sm text-danger' : 'text-sm text-ink-muted'}
        >
          {msg?.text ?? '음성 회선으로 보내 중간에 끊길 수 있습니다. 실패하면 이력에서 다시 보내기를 누르세요.'}
        </p>
        <Button
          type="submit"
          variant="primary"
          size="md"
          loading={submitting}
          icon={<Icon name="send" size={12} />}
        >
          팩스 보내기
        </Button>
      </div>
    </form>
  );
}
