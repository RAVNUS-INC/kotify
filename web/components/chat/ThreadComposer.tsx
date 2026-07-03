'use client';

import { useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useRouter } from 'next/navigation';
import { Button, Icon, Textarea } from '@/components/ui';
import { sendMessageClient } from '@/lib/chat';

export type ThreadComposerProps = {
  threadId: string;
  disabled?: boolean;
};

export function ThreadComposer({ threadId, disabled }: ThreadComposerProps) {
  const router = useRouter();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const trimmed = text.trim();
    if (!trimmed || sending || disabled) return;
    setSending(true);
    setError(null);
    try {
      await sendMessageClient(threadId, trimmed);
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
      <div className="flex items-center justify-between">
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
    </form>
  );
}
