'use client';

import { useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';

const MAX_BACKOFF_MS = 30_000;
const BASE_BACKOFF_MS = 1_000;

// 전달 상태 새로고침 최소 간격 — 서버 발행 창(services/events.publish_throttled)과 같다.
const DELIVERY_REFRESH_MIN_GAP_MS = 5_000;
// 새로고침해도 대기 목록이 그대로면 간격을 두 배씩 늘리는 상한. 예약 취소 캠페인처럼 대기로
// 남는 메시지가 열려 있어도 대량 발송 리포트 내내 창마다 새로고침하지 않게 한다.
const DELIVERY_REFRESH_MAX_GAP_MS = 60_000;
// 대기 메시지가 없어 흘려보낸 thread.updated 뒤 이 시간 안에 같은 대화에 대기 메시지가 새로
// 보이면 한 번 따라잡는다. 답장 직후 새로고침이 진행 중일 때 온 이벤트는 그 답장이 아직 없는
// 화면을 기준으로 판단되기 때문 — 새로고침 1회 왕복(목록 조회 포함)보다 넉넉하게 잡는다.
const MISSED_UPDATE_WINDOW_MS = 15_000;

const NO_PENDING: readonly string[] = [];

// 벽시계(Date.now)는 시스템 시각이 뒤로 가면 예약이 그만큼 밀려 대기에 묶인다 — 단조 시계.
const monotonicNow = () => performance.now();

export type ChatStreamOptions = {
  /** 열린 대화방 id. 목록만 볼 땐 생략. */
  threadId?: string;
  /**
   * 열린 대화방에서 결과 리포트를 기다리는 발신 메시지 id(lib/chat getPendingDeliveryIds).
   * 비어 있으면 전달 상태 이벤트(thread.updated)에 새로고침하지 않는다.
   */
  pendingDeliveryIds?: readonly string[];
};

type DeliveryRefresher = {
  /** 열린 대화와 그 대화의 전달 대기 메시지 id 가 (다시) 렌더됐다. */
  setView(threadId: string | undefined, pendingIds: readonly string[]): void;
  /** thread.updated 수신. */
  onUpdate(): void;
  /** SSE 구독이 열렸다(재연결 포함). */
  onConnect(): void;
  dispose(): void;
};

/**
 * 전달 상태 새로고침 스케줄러 — 모든 요청이 request() 한 곳을 지나 간격을 지킨다.
 *
 * - 대기 메시지가 없으면 새로고침하지 않는다(바뀔 게 없다).
 * - 직전 새로고침 뒤 MIN_GAP 이 안 지났으면 그 시점으로 미뤄 한 번에 합친다.
 * - 새로고침해도 대기 목록이 그대로였으면 간격을 두 배로(최대 MAX_GAP), 목록이 바뀌면 처음으로.
 * 이벤트가 올 때만 움직인다 — 폴링하지 않는다.
 */
function createDeliveryRefresher(
  refresh: () => void,
  initialThreadId: string | undefined,
  initialPending: readonly string[],
): DeliveryRefresher {
  let threadId = initialThreadId;
  let pending = new Set(initialPending);
  let gapMs = DELIVERY_REFRESH_MIN_GAP_MS;
  let lastRefreshAt: number | null = null;
  let lastRefreshKey: string | null = null;
  let missedUpdateAt: number | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let timerDueAt = 0;

  const pendingKey = () => Array.from(pending).sort().join('\n');

  const cancel = () => {
    if (timer) clearTimeout(timer);
    timer = null;
  };

  const fire = () => {
    timer = null;
    if (pending.size === 0) return;
    const key = pendingKey();
    gapMs =
      key === lastRefreshKey
        ? Math.min(gapMs * 2, DELIVERY_REFRESH_MAX_GAP_MS)
        : DELIVERY_REFRESH_MIN_GAP_MS;
    lastRefreshKey = key;
    lastRefreshAt = monotonicNow();
    refresh();
  };

  const request = () => {
    const now = monotonicNow();
    const dueAt = lastRefreshAt === null ? now : Math.max(now, lastRefreshAt + gapMs);
    if (timer && timerDueAt <= dueAt) return; // 같거나 이른 새로고침이 이미 잡혀 있다
    cancel();
    if (dueAt <= now) {
      fire();
      return;
    }
    timerDueAt = dueAt;
    timer = setTimeout(fire, dueAt - now);
  };

  return {
    setView(nextThreadId, ids) {
      const next = new Set(ids);
      if (nextThreadId !== threadId) {
        // 다른 대화로 옮겼다. 이동 요청보다 먼저 받은 이벤트는 새 화면에 이미 반영돼 있으니
        // 흘려보낸 이벤트·미뤄 둔 새로고침·백오프를 버린다 — 대량 발송 중 대화를 고를 때마다
        // 새로고침을 한 번 더 부르지 않게. 이동하는 동안 온 이벤트는 놓칠 수 있지만 드물고,
        // 발송이 이어지면 곧 오는 다음 이벤트가 (대기 메시지가 보이니) 새로고침한다.
        threadId = nextThreadId;
        pending = next;
        cancel();
        gapMs = DELIVERY_REFRESH_MIN_GAP_MS;
        lastRefreshAt = null;
        lastRefreshKey = null;
        missedUpdateAt = null;
        return;
      }
      const gained = ids.some((id) => !pending.has(id));
      const changed = gained || next.size !== pending.size;
      pending = next;
      if (!changed) return;
      gapMs = DELIVERY_REFRESH_MIN_GAP_MS;
      if (pending.size === 0) {
        cancel();
        return;
      }
      const missedRecently =
        gained &&
        missedUpdateAt !== null &&
        monotonicNow() - missedUpdateAt < MISSED_UPDATE_WINDOW_MS;
      if (missedRecently) missedUpdateAt = null;
      // 늘어난 간격으로 미뤄 둔 새로고침은 줄어든 간격으로 다시 잡는다 — 새 답장의 리포트가
      // 이전 대기 메시지의 백오프에 묶이지 않게.
      if (timer || missedRecently) {
        cancel();
        request();
      }
    },
    onUpdate() {
      if (pending.size === 0) {
        missedUpdateAt = monotonicNow();
        return;
      }
      request();
    },
    onConnect() {
      if (pending.size > 0) request();
    },
    dispose: cancel,
  };
}

/**
 * /api/chat/stream SSE 구독 — 이벤트를 받으면 router.refresh()로 server component 재실행을 유도.
 *
 * 새로고침 1회가 목록·상세 API(각각 하이웍스 외부 DB 조회)를 다시 부르므로 탭에서 한 번만
 * 구독한다(ChatLiveRefresh). Next 는 겹친 refresh 를 합치지 않고 모두 실행한다.
 * - message.new(고객 회신): 바로 새로고침.
 * - thread.updated(발신 전달 상태 변경): 서버가 창당 1회로 합쳐 보내지만 대량 발송 중엔 계속
 *   오므로 전달 대기 메시지가 보이는 화면만, 간격을 지켜 새로고침한다(createDeliveryRefresher).
 * - 구독이 열리면(재연결 포함) 대기 메시지가 있을 때 새로고침 — 구독 전·끊긴 동안 발행된
 *   이벤트는 받을 수 없다.
 *
 * 브라우저 자동 재연결 대신 명시적 exponential backoff로 reconnect storm 방지.
 * open 이벤트에서 attempts=0 리셋. cleanup 시 timer도 함께 취소.
 */
export function useChatStream({
  threadId,
  pendingDeliveryIds = NO_PENDING,
}: ChatStreamOptions = {}) {
  const router = useRouter();
  // 대화·대기 목록이 바뀌어도 연결 effect 를 다시 돌리지 않는다(재연결 없이 스케줄러에만 전달).
  const viewRef = useRef({ threadId, pendingDeliveryIds });
  const deliveryRef = useRef<DeliveryRefresher | null>(null);

  useEffect(() => {
    viewRef.current = { threadId, pendingDeliveryIds };
    deliveryRef.current?.setView(threadId, pendingDeliveryIds);
  }, [threadId, pendingDeliveryIds]);

  useEffect(() => {
    if (typeof window === 'undefined' || !('EventSource' in window)) return;

    const view = viewRef.current;
    const delivery = createDeliveryRefresher(
      () => router.refresh(),
      view.threadId,
      view.pendingDeliveryIds,
    );
    deliveryRef.current = delivery;
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

      es.addEventListener('message.new', () => router.refresh());
      es.addEventListener('thread.updated', () => delivery.onUpdate());
      es.addEventListener('open', () => {
        attempts = 0;
        delivery.onConnect();
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
      delivery.dispose();
      deliveryRef.current = null;
    };
  }, [router]);
}
