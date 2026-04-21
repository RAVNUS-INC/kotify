'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

/**
 * /api/chat/stream SSE 구독. message.new / thread.updated 이벤트 수신 시
 * router.refresh()로 server component 재실행을 유도.
 *
 * Phase 6d: 연결 확립. 실제 이벤트 발행은 Phase 7+.
 */
export function useChatStream() {
  const router = useRouter();

  useEffect(() => {
    if (typeof window === 'undefined' || !('EventSource' in window)) return;

    let es: EventSource | null = null;
    try {
      es = new EventSource('/api/chat/stream');
    } catch {
      return;
    }

    const refresh = () => router.refresh();
    es.addEventListener('message.new', refresh);
    es.addEventListener('thread.updated', refresh);
    es.addEventListener('error', () => {
      // 네트워크 오류 — 브라우저가 자동 재연결
    });

    return () => {
      es?.removeEventListener('message.new', refresh);
      es?.removeEventListener('thread.updated', refresh);
      es?.close();
    };
  }, [router]);
}
