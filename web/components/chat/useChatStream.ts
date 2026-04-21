'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

const MAX_BACKOFF_MS = 30_000;
const BASE_BACKOFF_MS = 1_000;

/**
 * /api/chat/stream SSE 구독. message.new / thread.updated 이벤트 수신 시
 * router.refresh()로 server component 재실행을 유도.
 *
 * 브라우저 자동 재연결 대신 명시적 exponential backoff로 reconnect storm 방지.
 * open 이벤트에서 attempts=0 리셋. cleanup 시 timer도 함께 취소.
 */
export function useChatStream() {
  const router = useRouter();

  useEffect(() => {
    if (typeof window === 'undefined' || !('EventSource' in window)) return;

    let es: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let attempts = 0;
    let cancelled = false;

    const connect = () => {
      if (cancelled) return;
      try {
        es = new EventSource('/api/chat/stream');
      } catch {
        return;
      }

      const refresh = () => router.refresh();
      es.addEventListener('message.new', refresh);
      es.addEventListener('thread.updated', refresh);
      es.addEventListener('open', () => {
        attempts = 0;
      });
      es.addEventListener('error', () => {
        if (!es) return;
        es.close();
        es = null;
        if (cancelled) return;
        const delay = Math.min(
          MAX_BACKOFF_MS,
          BASE_BACKOFF_MS * 2 ** attempts,
        );
        attempts += 1;
        retryTimer = setTimeout(connect, delay);
      });
    };

    connect();

    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      if (es) es.close();
    };
  }, [router]);
}
