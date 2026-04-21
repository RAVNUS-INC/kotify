'use client';

import { useEffect, useRef } from 'react';
import type { ChatThreadDetail } from '@/types/chat';
import { MessageBubble } from './MessageBubble';
import { ThreadComposer } from './ThreadComposer';
import { useChatStream } from './useChatStream';

export type ThreadViewProps = {
  thread: ChatThreadDetail;
};

export function ThreadView({ thread }: ThreadViewProps) {
  useChatStream();

  const scrollRef = useRef<HTMLDivElement>(null);
  const lastMessageId = thread.messages[thread.messages.length - 1]?.id;

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lastMessageId]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-line bg-surface">
      <div
        ref={scrollRef}
        className="flex-1 space-y-3 overflow-y-auto px-5 py-6"
        role="log"
        aria-live="polite"
        aria-label="대화 메시지"
      >
        {thread.messages.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-ink-muted">
            아직 주고받은 메시지가 없습니다.
          </div>
        ) : (
          thread.messages.map((m) => (
            <MessageBubble key={m.id} side={m.side} kind={m.kind} timestamp={m.time}>
              {m.text}
            </MessageBubble>
          ))
        )}
      </div>

      <ThreadComposer threadId={thread.id} />
    </div>
  );
}
