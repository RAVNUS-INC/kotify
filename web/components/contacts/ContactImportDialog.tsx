'use client';

import { useRef, useState, type ChangeEvent, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import {
  Button,
  Drawer,
  Field,
  Icon,
  Radio,
} from '@/components/ui';
import {
  importContactsClient,
  type ImportMode,
  type ImportResult,
} from '@/lib/contacts-client';

export type ContactImportDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

const MODE_DESC: Record<ImportMode, string> = {
  skip: '전화번호가 같은 연락처는 건너뜀 (권장)',
  update: '전화번호가 같은 연락처는 덮어씀',
  create: '중복 검사 없이 전부 새로 생성',
};

/**
 * CSV 업로드 UI — multipart POST `/api/contacts/import`.
 * 결과(`created/updated/skipped/invalid/errors/invalidPreview`) 를 그대로 표시.
 */
export function ContactImportDialog({
  open,
  onOpenChange,
}: ContactImportDialogProps) {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<ImportMode>('skip');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setFile(null);
    setResult(null);
    setError(null);
    setSubmitting(false);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const onPickFile = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null;
    setFile(f);
    setResult(null);
    setError(null);
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const r = await importContactsClient(file, mode);
      setResult(r);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : '업로드 실패');
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
      title="CSV 가져오기"
      description="name,phone,email,department,notes 컬럼 지원 — UTF-8 (BOM 허용)."
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
              form="contact-import-form"
              loading={submitting}
              disabled={!file}
              icon={<Icon name="upload" size={12} />}
            >
              업로드
            </Button>
          ) : null}
        </div>
      }
    >
      {!result ? (
        <form
          id="contact-import-form"
          onSubmit={onSubmit}
          className="space-y-4"
        >
          <Field
            label="CSV 파일"
            hint="예) name,phone,email,department,notes 헤더."
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,text/csv"
              onChange={onPickFile}
              disabled={submitting}
              className="block w-full text-sm"
            />
          </Field>
          <Field label="중복 처리 모드" hint={MODE_DESC[mode]}>
            <div className="flex flex-col gap-1">
              {(['skip', 'update', 'create'] as const).map((m) => (
                <Radio
                  key={m}
                  name="import-mode"
                  value={m}
                  checked={mode === m}
                  onChange={() => setMode(m)}
                  disabled={submitting}
                  label={
                    m === 'skip'
                      ? '건너뛰기 (skip)'
                      : m === 'update'
                        ? '덮어쓰기 (update)'
                        : '새로 생성 (create)'
                  }
                />
              ))}
            </div>
          </Field>
          {error ? (
            <div className="rounded border border-danger/30 bg-danger/5 p-2 text-sm text-danger" role="alert">
              {error}
            </div>
          ) : null}
        </form>
      ) : (
        <div className="space-y-4">
          <div className="rounded-lg border border-line bg-gray-1 p-4">
            <h3 className="mb-2 text-sm font-semibold text-ink">업로드 결과</h3>
            <ul className="space-y-1 text-sm text-ink-muted">
              <li>
                새로 생성:{' '}
                <strong className="text-ok">{result.created}</strong>
              </li>
              <li>
                업데이트:{' '}
                <strong className="text-brand">{result.updated}</strong>
              </li>
              <li>
                건너뜀: <strong>{result.skipped}</strong>
              </li>
              <li>
                잘못된 행:{' '}
                <strong className="text-danger">{result.invalid}</strong>
              </li>
            </ul>
          </div>
          {result.errors.length > 0 ? (
            <div className="rounded-lg border border-warning/30 bg-warning/5 p-3 text-[12.5px] text-warning">
              <div className="mb-1 font-semibold">경고 ({result.errors.length})</div>
              <ul className="space-y-1">
                {result.errors.slice(0, 10).map((err, i) => (
                  <li key={i}>{err}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {result.invalidPreview.length > 0 ? (
            <div className="rounded-lg border border-line bg-surface p-3 text-[12px] text-ink-muted">
              <div className="mb-1 font-semibold text-ink">잘못된 행 미리보기</div>
              <ul className="space-y-1">
                {result.invalidPreview.slice(0, 10).map((row, i) => (
                  <li key={i} className="font-mono">
                    {row.row ? `행 ${row.row}: ` : ''}
                    {row.error ?? JSON.stringify(row)}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <Button variant="secondary" size="md" onClick={reset} full>
            다른 파일 업로드
          </Button>
        </div>
      )}
    </Drawer>
  );
}
