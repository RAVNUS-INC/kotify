'use client';

import { useMemo, useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { MessageBubble } from '@/components/chat';
import {
  Button,
  Check,
  ChipField,
  Editor,
  EditorToolbarButton,
  EditorToolbarDivider,
  Field,
  Icon,
  Input,
  Radio,
} from '@/components/ui';
import { cn } from '@/lib/cn';
import { DeviceMockup } from './DeviceMockup';

type SendMode = 'now' | 'schedule';

type Sender = { value: string; label: string };

// TODO Phase 8: /api/numbers 에서 불러오기
const SENDERS: ReadonlyArray<Sender> = [
  { value: '1588-1234', label: '1588-1234 · 대표번호' },
  { value: '02-3456-7890', label: '02-3456-7890 · 인사팀' },
  { value: '010-1234-5678', label: '010-1234-5678 · 김운영' },
];

const SMS_BYTES = 90;
const LMS_BYTES = 2000;

function computeEstimate(message: string, recipientCount: number) {
  const bytes = new TextEncoder().encode(message).length;
  let channel: 'SMS' | 'LMS' | 'MMS' = 'SMS';
  let perUnit = 8;
  if (bytes > LMS_BYTES) {
    channel = 'MMS';
    perUnit = 100;
  } else if (bytes > SMS_BYTES) {
    channel = 'LMS';
    perUnit = 32;
  }
  const cost = recipientCount * perUnit;
  const bytesState: 'warn' | 'err' | undefined =
    bytes > LMS_BYTES ? 'err' : bytes > SMS_BYTES ? 'warn' : undefined;
  return { bytes, channel, perUnit, cost, bytesState };
}

export function ComposeForm() {
  const router = useRouter();
  const [sender, setSender] = useState<string>('1588-1234');
  const [recipients, setRecipients] = useState<string[]>([]);
  const [message, setMessage] = useState('');
  const [mode, setMode] = useState<SendMode>('now');
  const [sendAt, setSendAt] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { bytes, channel, cost, bytesState } = useMemo(
    () => computeEstimate(message, recipients.length),
    [message, recipients.length],
  );

  const recipientsState: 'warn' | 'err' | undefined =
    recipients.length > 1000 ? 'err' : recipients.length > 500 ? 'warn' : undefined;

  const canSubmit =
    sender !== '' &&
    recipients.length > 0 &&
    recipients.length <= 1000 &&
    message.trim() !== '' &&
    bytesState !== 'err' &&
    (mode === 'now' || sendAt !== '') &&
    confirmed &&
    !submitting;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch('/api/campaigns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sender,
          recipients,
          message,
          sendAt: mode === 'schedule' ? sendAt : null,
          channel,
        }),
      });
      const json = (await res.json()) as {
        data?: { id: string };
        error?: { code: string; message: string };
      };
      if (!res.ok || json.error) {
        throw new Error(json.error?.message ?? `HTTP ${res.status}`);
      }
      router.push('/campaigns');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  };

  // SMS/LMS/MMS는 모두 'sms' 버블로 표시. RCS 프리뷰는 Phase 후속에서 실제
  // 발신 RCS 지원 여부 확인 후 분기.
  const previewKind = 'sms' as const;

  return (
    <form onSubmit={onSubmit} className="mt-6 grid gap-6 lg:grid-cols-[560px_1fr]">
      <div className="flex flex-col gap-5">
        <Field label="발신번호" htmlFor="sender" required>
          <select
            id="sender"
            value={sender}
            onChange={(e) => setSender(e.target.value)}
            className="h-9 w-full rounded border border-gray-4 bg-surface px-3 text-md focus:border-brand focus:shadow-[0_0_0_3px_rgba(59,0,139,0.08)] focus:outline-none"
          >
            {SENDERS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </Field>

        <Field
          label="수신자"
          htmlFor="recipients"
          required
          hint="이름·번호·그룹 입력 후 Enter 또는 쉼표. 캠페인당 최대 1,000명"
          counter={{
            value: `${recipients.length} / 1,000명`,
            state: recipientsState,
          }}
        >
          <ChipField
            id="recipients"
            aria-label="수신자 목록"
            value={recipients}
            onChange={setRecipients}
            placeholder="예) 010-1234-5678"
            maxChips={1000}
            invalid={recipientsState === 'err'}
          />
        </Field>

        <Field label="CSV 업로드" hint="수신자 목록을 일괄 추가 (준비 중)">
          <Button
            type="button"
            variant="secondary"
            size="md"
            icon={<Icon name="upload" size={12} />}
            disabled
          >
            CSV 파일 선택
          </Button>
        </Field>

        <Field
          label="메시지"
          htmlFor="msg"
          required
          hint={`자동 채널: ${channel} · ${bytes} bytes`}
          counter={{
            value: `${bytes} bytes`,
            state: bytesState,
          }}
          error={
            bytesState === 'err'
              ? 'MMS 본문 한계(2,000 bytes)를 초과했습니다'
              : undefined
          }
        >
          <Editor
            id="msg"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="본문을 입력하세요..."
            invalid={bytesState === 'err'}
            rows={6}
            toolbar={
              <>
                <EditorToolbarButton
                  icon={<Icon name="hash" size={12} />}
                  disabled
                >
                  변수
                </EditorToolbarButton>
                <EditorToolbarButton
                  icon={<Icon name="fileText" size={12} />}
                  disabled
                >
                  템플릿
                </EditorToolbarButton>
                <EditorToolbarDivider />
                <EditorToolbarButton
                  icon={<Icon name="image" size={12} />}
                  disabled
                >
                  이미지
                </EditorToolbarButton>
                <EditorToolbarButton
                  icon={<Icon name="link" size={12} />}
                  disabled
                >
                  링크
                </EditorToolbarButton>
              </>
            }
            footer={
              <>
                <span className="font-mono">
                  {bytes} bytes · {channel}
                </span>
                <span className="font-mono text-ink-dim">
                  예상 {recipients.length}건 · ₩
                  {cost.toLocaleString('ko-KR')}
                </span>
              </>
            }
          />
        </Field>

        <Field label="발송 방식" required>
          <div className="flex flex-col gap-2">
            <Radio
              name="mode"
              value="now"
              checked={mode === 'now'}
              onChange={() => setMode('now')}
              label="즉시 발송"
              sub="접수 후 바로 전송"
            />
            <Radio
              name="mode"
              value="schedule"
              checked={mode === 'schedule'}
              onChange={() => setMode('schedule')}
              label="예약"
              sub="지정 시간에 전송"
            />
            {mode === 'schedule' && (
              <Input
                type="datetime-local"
                aria-label="예약 발송 시간"
                value={sendAt}
                onChange={(e) => setSendAt(e.target.value)}
                className="ml-6 mt-1 max-w-[260px]"
              />
            )}
          </div>
        </Field>

        <Field label="확인" required>
          <Check
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            label="수신자 모두에게 발송됨을 확인했습니다"
            sub={
              recipients.length > 100
                ? '고위험 대량 발송 · 접수 후 취소 불가'
                : undefined
            }
          />
        </Field>

        {error && (
          <div
            role="alert"
            className="rounded border border-danger/30 bg-danger-bg px-3 py-2 text-sm text-danger"
          >
            {error}
          </div>
        )}

        <div className="flex items-center justify-end gap-2 pt-2">
          <Button
            type="button"
            variant="ghost"
            onClick={() => router.push('/')}
          >
            취소
          </Button>
          <Button
            type="submit"
            variant="primary"
            icon={<Icon name="send" size={12} />}
            loading={submitting}
            disabled={!canSubmit}
          >
            {mode === 'schedule' ? '예약 등록' : '발송'}
          </Button>
        </div>
      </div>

      <aside className="lg:sticky lg:top-6 lg:self-start">
        <div className="mb-3 font-mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-ink-dim">
          미리보기 · {channel}
        </div>
        <DeviceMockup
          frame="ios"
          senderName={sender}
          timeLabel={mode === 'schedule' && sendAt ? sendAt.replace('T', ' ') : '지금'}
        >
          <MessageBubble kind={previewKind} side="them">
            {message.trim() ? (
              message
            ) : (
              <span className={cn('text-gray-5')}>
                메시지를 입력하면 여기에 표시됩니다.
              </span>
            )}
          </MessageBubble>
        </DeviceMockup>
        <div className="mt-4 rounded-lg border border-line bg-surface p-3 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-ink-muted">수신자</span>
            <span className="font-mono">{recipients.length}명</span>
          </div>
          <div className="mt-1 flex items-center justify-between">
            <span className="text-ink-muted">채널</span>
            <span className="font-mono">{channel}</span>
          </div>
          <div className="mt-1 flex items-center justify-between">
            <span className="text-ink-muted">예상 비용</span>
            <span className="font-mono font-semibold text-ink">
              ₩{cost.toLocaleString('ko-KR')}
            </span>
          </div>
        </div>
      </aside>
    </form>
  );
}
