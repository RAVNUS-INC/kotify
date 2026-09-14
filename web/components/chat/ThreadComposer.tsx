'use client';

import { useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useRouter } from 'next/navigation';
import { Button, Icon, Radio, Textarea } from '@/components/ui';
import { sendMessageClient } from '@/lib/chat';
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

  const submit = async () => {
    const trimmed = text.trim();
    if (!trimmed || sending || disabled) return;
    setSending(true);
    setError(null);
    try {
      await sendMessageClient(threadId, trimmed, sendChannel);
      setText('');
      router.refresh();
      textareaRef.current?.focus();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
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
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="메시지 입력 · Enter로 줄바꿈, ⌘/Shift+Enter로 발송"
        rows={3}
        disabled={disabled || sending}
        aria-label="메시지 입력"
      />
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
          <div className="font-mono text-[11px] text-ink-dim">
            {text.length}자
          </div>
          <Button
            type="submit"
            variant="primary"
            size="sm"
            icon={<Icon name="send" size={12} />}
            loading={sending}
            disabled={!text.trim() || disabled}
          >
            발송
          </Button>
        </div>
      </div>
    </form>
  );
}
