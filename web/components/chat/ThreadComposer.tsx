'use client';

import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useRouter } from 'next/navigation';
import { Button, Icon, Radio, Textarea } from '@/components/ui';
import { sendMessageClient } from '@/lib/chat';
import { ApiError } from '@/lib/api-error';
import { validateReplyClient, type ReplyValidation } from '@/lib/reply-validation';
import type { SendChannel } from '@/types/chat';

export type ThreadComposerProps = {
  threadId: string;
  /** 이 번호로 가장 최근에 전달 성공한 전송 방식. 없으면 새 발송 화면과 같은 RCS. */
  defaultSendChannel?: SendChannel;
  disabled?: boolean;
};

// 새 발송 화면(ComposeForm)과 같은 순서·구분·기본값. 답장은 90바이트 단문이라 일반은 SMS.
const SEND_CHANNEL_OPTIONS: ReadonlyArray<{ value: SendChannel; label: string }> = [
  { value: 'sms', label: '일반 SMS' },
  { value: 'rcs', label: 'RCS' },
];
const FALLBACK_SEND_CHANNEL: SendChannel = 'rcs';
const REPLY_MAX_BYTES = 90;
const VALIDATION_DELAY_MS = 300;

type ValidationState = {
  text: string;
  result: ReplyValidation | null;
  failure: string | null;
};

export function ThreadComposer({
  threadId,
  defaultSendChannel,
  disabled,
}: ThreadComposerProps) {
  const router = useRouter();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [text, setText] = useState('');
  // 기본값 = 이 번호의 최근 전달 성공 방식, 이력이 없으면 RCS. 체크 상태가 발송 버튼 옆에
  // 보여 어떤 방식으로 나가는지 드러난다. 대화방이 바뀌면 ThreadView 가 key 로 리셋한다.
  const [sendChannel, setSendChannel] = useState<SendChannel>(
    defaultSendChannel ?? FALLBACK_SEND_CHANNEL,
  );
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validation, setValidation] = useState<ValidationState | null>(null);
  const [validationAttempt, setValidationAttempt] = useState(0);
  const validationGeneration = useRef(0);
  const sendingRef = useRef(false);
  const lengthHintId = useId();
  const validationErrorId = useId();
  const trimmed = text.trim();

  useEffect(() => {
    const generation = ++validationGeneration.current;
    if (!trimmed) {
      setValidation(null);
      return;
    }
    const controller = new AbortController();
    setValidation({ text: trimmed, result: null, failure: null });
    const timer = setTimeout(() => {
      void validateReplyClient(trimmed, controller.signal)
        .then((result) => {
          if (controller.signal.aborted || generation !== validationGeneration.current) return;
          setValidation({ text: trimmed, result, failure: null });
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted || generation !== validationGeneration.current) return;
          const reason = err instanceof Error ? err.message : '통신 오류';
          setValidation({
            text: trimmed,
            result: null,
            failure: `길이를 확인하지 못했습니다 (${reason}). 다시 확인해 주세요.`,
          });
        });
    }, VALIDATION_DELAY_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [trimmed, validationAttempt]);

  // 새 입력 직후 effect 가 실행되기 전에도 이전 본문의 검증 결과로 발송하면 안 된다.
  const currentValidation = validation?.text === trimmed ? validation : null;
  const result = currentValidation?.result;
  const validationError = currentValidation?.failure ?? (
    result && !result.valid
      ? result.error ?? '발송할 수 없는 내용입니다. 입력 내용을 확인해 주세요.'
      : null
  );
  const canSend = Boolean(trimmed && result?.valid && !currentValidation?.failure);
  const checking = Boolean(trimmed && !result && !currentValidation?.failure);
  const lengthHint = !trimmed
    ? `현재 0 / ${REPLY_MAX_BYTES}바이트`
    : checking
      ? '길이 확인 중'
      : result?.byteLength != null
        ? `현재 ${result.byteLength} / ${result.maxBytes}바이트`
        : `길이 확인 불가 · 최대 ${REPLY_MAX_BYTES}바이트`;

  const submit = async () => {
    if (!canSend || sendingRef.current || sending || disabled) return;
    sendingRef.current = true;
    setSending(true);
    setError(null);
    try {
      await sendMessageClient(threadId, trimmed, sendChannel);
      setText('');
      router.refresh();
      textareaRef.current?.focus();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      if (err instanceof ApiError && ['send_failed', 'send_status_unknown'].includes(err.code)) {
        // 서버에 남은 발송 이력을 표시한다. 접수 미확정 응답은 재발송하지 않는다.
        router.refresh();
      }
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void submit();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter=줄바꿈(기본 동작), Cmd/Ctrl+Enter 또는 Shift+Enter=발송.
    // 한글 조합 중(isComposing) Enter 는 조합 확정이므로 발송하지 않는다.
    if (
      e.key === 'Enter' &&
      (e.metaKey || e.ctrlKey || e.shiftKey) &&
      !e.nativeEvent.isComposing
    ) {
      e.preventDefault();
      void submit();
    }
  };

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2 border-t border-line bg-surface p-4">
      {error && (
        <div
          role="alert"
          className="rounded border border-danger/30 bg-danger-bg px-2 py-1 text-xs text-danger"
        >
          {error}
        </div>
      )}
      <Textarea
        ref={textareaRef}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setError(null);
        }}
        onKeyDown={onKeyDown}
        placeholder="메시지 입력 · Enter로 줄바꿈, ⌘/Shift+Enter로 발송"
        rows={3}
        disabled={disabled || sending}
        aria-label="메시지 입력"
        aria-describedby={`${lengthHintId}${validationError ? ` ${validationErrorId}` : ''}`}
        invalid={Boolean(validationError)}
      />
      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-ink-dim">
        <span>답장은 최대 {REPLY_MAX_BYTES}바이트 · 한글 약 45자, 영문 약 90자</span>
        <span id={lengthHintId} role="status" aria-live="polite" className="font-mono">
          {lengthHint}
        </span>
      </div>
      {validationError && (
        <div id={validationErrorId} role="alert" className="text-xs text-danger">
          {validationError}
          {currentValidation?.failure && (
            <button
              type="button"
              onClick={() => setValidationAttempt((attempt) => attempt + 1)}
              disabled={disabled || sending}
              className="ml-2 underline"
            >
              다시 확인
            </button>
          )}
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div
          role="radiogroup"
          aria-label="전송 방식"
          className="flex flex-wrap items-center gap-x-3 gap-y-1"
        >
          {SEND_CHANNEL_OPTIONS.map((opt) => (
            <Radio
              key={opt.value}
              name="replySendChannel"
              value={opt.value}
              checked={sendChannel === opt.value}
              onChange={() => setSendChannel(opt.value)}
              disabled={disabled || sending}
              label={opt.label}
              className="whitespace-nowrap"
            />
          ))}
          {defaultSendChannel && sendChannel === defaultSendChannel && (
            <span className="whitespace-nowrap text-[11px] text-ink-dim">
              최근 전달 성공 방식
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <Button
            type="submit"
            variant="primary"
            size="sm"
            icon={<Icon name="send" size={12} />}
            loading={sending}
            disabled={!canSend || disabled}
          >
            발송
          </Button>
        </div>
      </div>
    </form>
  );
}
