'use client';

import { Fragment, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import type { ChatThreadDetail } from '@/types/chat';
import { markReadClient, withDateDividers } from '@/lib/chat';
import { ChatDateDivider } from './ChatDateDivider';
import { MessageBubble } from './MessageBubble';
import { ThreadComposer } from './ThreadComposer';

export type ThreadViewProps = {
  thread: ChatThreadDetail;
};

// 실시간 갱신(SSE)은 여기서 구독하지 않는다 — 페이지의 ChatLiveRefresh 가 탭당 하나로 맡는다.
export function ThreadView({ thread }: ThreadViewProps) {
  const router = useRouter();

  const scrollRef = useRef<HTMLDivElement>(null);
  const lastMessageId = thread.messages[thread.messages.length - 1]?.id;

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lastMessageId]);

  // 화면에 실제로 전달된 회신까지만 읽는다. 새 회신이 와도 unread가 true로 유지될 수 있다.
  const threadId = thread.id;
  const wasUnread = thread.unread === true;
  const lastInboundMessageId = thread.lastInboundMessageId;
  useEffect(() => {
    if (!wasUnread || lastInboundMessageId == null) return;
    let active = true;
    void markReadClient(threadId, lastInboundMessageId)
      .then(() => {
        // 서버 컴포넌트(목록·안읽음 배지) 재요청 — 새로고침 없이 즉시 반영.
        if (active) router.refresh();
      })
      .catch(() => {
        // 읽음 표시 실패는 치명적이지 않음 — silent
      });
    return () => { active = false; };
  }, [threadId, wasUnread, lastInboundMessageId, router]);

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
          // 구분선은 그날 첫 메시지의 key 에 묶는다. 같은 날 메시지가 끝에 붙으면 구분선 노드가
          // 그대로라 aria-live 대화 영역이 이미 읽은 날짜를 다시 알리지 않는다.
          withDateDividers(thread.messages).map(({ message: m, dividerDate }) => (
            <Fragment key={m.id}>
              {dividerDate && <ChatDateDivider date={dividerDate} />}
              <MessageBubble
                side={m.side}
                kind={m.kind}
                status={m.status}
                timestamp={m.time}
                senderName={m.senderName}
              >
                {m.text}
              </MessageBubble>
            </Fragment>
          ))
        )}
      </div>

      {/* key: 대화방이 바뀌면 입력·전송 방식 상태를 새 번호 기준으로 리셋. */}
      <ThreadComposer
        key={thread.id}
        threadId={thread.id}
        defaultSendChannel={thread.defaultSendChannel}
      />
    </div>
  );
}
