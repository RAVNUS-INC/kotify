'use client';

import { useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import type { ChatThreadDetail } from '@/types/chat';
import { markReadClient } from '@/lib/chat';
import { MessageBubble } from './MessageBubble';
import { ThreadComposer } from './ThreadComposer';
import { useChatStream } from './useChatStream';

export type ThreadViewProps = {
  thread: ChatThreadDetail;
};

export function ThreadView({ thread }: ThreadViewProps) {
  useChatStream();
  const router = useRouter();

  const scrollRef = useRef<HTMLDivElement>(null);
  const lastMessageId = thread.messages[thread.messages.length - 1]?.id;

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lastMessageId]);

  // 스레드 진입 시 자동 읽음 처리 (unread인 경우만)
  const threadId = thread.id;
  const wasUnread = thread.unread === true;
  useEffect(() => {
    if (!wasUnread) return;
    void markReadClient(threadId)
      .then(() => {
        // 서버 컴포넌트(목록·안읽음 배지) 재요청 — 새로고침 없이 즉시 반영.
        router.refresh();
      })
      .catch(() => {
        // 읽음 표시 실패는 치명적이지 않음 — silent
      });
  }, [threadId, wasUnread, router]);

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
