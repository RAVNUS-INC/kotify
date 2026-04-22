'use client';

import { useRef, useState, type ChangeEvent } from 'react';
import { Button, Icon } from '@/components/ui';
import {
  uploadCampaignAttachmentClient,
  type UploadedAttachment,
} from '@/lib/campaigns-client';

export type AttachmentPickerProps = {
  /** 현재 선택된 첨부 (없으면 null). */
  value: UploadedAttachment | null;
  onChange: (next: UploadedAttachment | null) => void;
  disabled?: boolean;
};

/**
 * MMS 첨부 이미지 선택 → 즉시 서버 업로드(전처리+msghub 등록) → 미리보기.
 *
 * 정책:
 *  - 서버가 10 MiB 상한 방어하지만 클라이언트에서도 빠른 피드백용 가드.
 *  - 업로드 성공 후엔 `value` 로 attachmentId + URL 을 부모에게 전달.
 *  - 재선택 시 기존 attachment 는 폐기 (서버에 orphan 으로 남지만 dispatch
 *    전 attachment 는 CASCADE/GC 대상).
 */
const CLIENT_SOFT_LIMIT = 10 * 1024 * 1024;

export function AttachmentPicker({
  value,
  onChange,
  disabled = false,
}: AttachmentPickerProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pick = () => fileInputRef.current?.click();

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setError(null);
    if (f.size > CLIENT_SOFT_LIMIT) {
      setError('원본이 너무 큽니다 (최대 10MB)');
      return;
    }
    setUploading(true);
    try {
      const uploaded = await uploadCampaignAttachmentClient(f);
      onChange(uploaded);
    } catch (err) {
      setError(err instanceof Error ? err.message : '업로드 실패');
    } finally {
      setUploading(false);
      // 같은 파일 재선택 가능하도록 reset.
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const clear = () => {
    onChange(null);
    setError(null);
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <input
          ref={fileInputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          onChange={onFile}
          disabled={disabled || uploading}
          className="hidden"
        />
        {!value ? (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            icon={<Icon name="upload" size={12} />}
            onClick={pick}
            loading={uploading}
            disabled={disabled}
          >
            {uploading ? '업로드 중…' : '이미지 첨부 (MMS)'}
          </Button>
        ) : (
          <>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              icon={<Icon name="edit" size={12} />}
              onClick={pick}
              disabled={disabled || uploading}
              loading={uploading}
            >
              교체
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              icon={<Icon name="x" size={12} />}
              onClick={clear}
              disabled={disabled || uploading}
            >
              제거
            </Button>
          </>
        )}
      </div>

      {value ? (
        <div className="flex items-start gap-3 rounded border border-line bg-gray-1 p-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={value.url}
            alt={value.originalFilename}
            className="h-24 w-24 shrink-0 rounded object-cover"
          />
          <div className="min-w-0 flex-1 text-[12.5px] text-ink-muted">
            <div className="truncate text-ink">{value.originalFilename}</div>
            <div className="mt-0.5 font-mono">
              {value.width} × {value.height} ·{' '}
              {(value.sizeBytes / 1024).toFixed(1)} KB
            </div>
            <div className="mt-0.5 text-[11px] text-ink-dim">
              첨부된 이미지는 MMS 로 전송됩니다. RCS 지원 번호에는 RCS 이미지로
              대체 전송될 수 있습니다.
            </div>
          </div>
        </div>
      ) : null}

      {error ? (
        <div
          className="rounded border border-danger/30 bg-danger/5 p-2 text-[12.5px] text-danger"
          role="alert"
        >
          {error}
        </div>
      ) : null}
    </div>
  );
}
