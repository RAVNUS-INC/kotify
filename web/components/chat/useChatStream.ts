'use client';

import { useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';

const MAX_BACKOFF_MS = 30_000;
const BASE_BACKOFF_MS = 1_000;

// 전달 상태 새로고침 최소 간격 — 서버 발행 창(services/events.publish_throttled)과 같다.
const DELIVERY_REFRESH_MIN_GAP_MS = 5_000;
// 새로고침해도 감시 목록이 그대로면 간격을 두 배씩 늘리는 상한. 복구되지 않는 실패 이력이
// 열려 있어도 대량 발송 리포트 내내 창마다 새로고침하지 않게 한다.
const DELIVERY_REFRESH_MAX_GAP_MS = 60_000;
// 대기 메시지가 없어 흘려보낸 thread.updated 뒤 이 시간 안에 같은 대화에 대기 메시지가 새로
// 보이면 한 번 따라잡는다. 답장 직후 새로고침이 진행 중일 때 온 이벤트는 그 답장이 아직 없는
// 화면을 기준으로 판단되기 때문 — 새로고침 1회 왕복(목록 조회 포함)보다 넉넉하게 잡는다.
const MISSED_UPDATE_WINDOW_MS = 15_000;

const NO_DELIVERY_IDS: readonly string[] = [];

// 벽시계(Date.now)는 시스템 시각이 뒤로 가면 예약이 그만큼 밀려 대기에 묶인다 — 단조 시계.
const monotonicNow = () => performance.now();

export type ChatStreamOptions = {
  /** 열린 대화방 id. 목록만 볼 땐 생략. */
  threadId?: string;
  /**
   * 열린 대화방에서 상태를 갱신할 대기·실패 발신 메시지 id(lib/chat getDeliveryRefreshIds).
   * 비어 있으면 전달 상태 이벤트(thread.updated)에 새로고침하지 않는다.
   */
  deliveryRefreshIds?: readonly string[];
};

type DeliveryRefresher = {
  /** 열린 대화와 그 대화의 대기·실패 메시지 id 가 (다시) 렌더됐다. */
  setView(threadId: string | undefined, pendingIds: readonly string[]): void;
  /** thread.updated 수신. */
  onUpdate(): void;
  /** SSE 구독이 열렸다(재연결 포함). */
  onConnect(): void;
  dispose(): void;
};

/**
 * 전달 상태 이벤트 스케줄러 — request()에서 간격을 지킨다. 연결 복구는 즉시 한 번 갱신한다.
 *
 * - 전달 상태 이벤트는 대기·실패 메시지가 있을 때만 새로고침한다.
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
  let lastUpdateAt: number | null = null;
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
        // 이전 대화의 타이머·백오프는 새 대화에 적용하지 않는다. 다만 상세 조회 뒤 렌더 전에
        // 도착한 이벤트일 수 있으므로 최근 이벤트는 새 화면에서도 한 번 따라잡는다. 서버 조회와
        // 이벤트의 선후를 알 수 없어 최근 이벤트가 있으면 보수적으로 갱신한다.
        threadId = nextThreadId;
        pending = next;
        cancel();
        gapMs = DELIVERY_REFRESH_MIN_GAP_MS;
        lastRefreshAt = null;
        lastRefreshKey = null;
        missedUpdateAt = null;
        if (
          pending.size > 0 &&
          lastUpdateAt !== null &&
          monotonicNow() - lastUpdateAt < MISSED_UPDATE_WINDOW_MS
        ) {
          request();
        }
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
      lastUpdateAt = monotonicNow();
      if (pending.size === 0) {
        missedUpdateAt = lastUpdateAt;
        return;
      }
      request();
    },
    onConnect() {
      // 회신 이벤트는 재생되지 않으므로 목록·확정된 대화도 연결마다 따라잡는다.
      // 이전 전달 상태의 백오프에 복구를 묶거나 기존 타이머와 중복 갱신하지 않는다.
      cancel();
      gapMs = DELIVERY_REFRESH_MIN_GAP_MS;
      lastRefreshKey = pending.size > 0 ? pendingKey() : null;
      lastRefreshAt = monotonicNow();
      refresh();
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
 *   오므로 대기·실패 메시지가 보이는 화면만, 간격을 지켜 새로고침한다(createDeliveryRefresher).
 * - 구독이 열리면(재연결 포함) 화면 상태와 무관하게 한 번 새로고침한다. 구독 전·끊긴 동안
 *   발행된 고객 회신과 발신 상태 이벤트는 재생되지 않는다.
 *
 * 브라우저 자동 재연결 대신 명시적 exponential backoff로 reconnect storm 방지.
 * open 이벤트에서 attempts=0 리셋. cleanup 시 timer도 함께 취소.
 */
export function useChatStream({
  threadId,
  deliveryRefreshIds = NO_DELIVERY_IDS,
}: ChatStreamOptions = {}) {
  const router = useRouter();
  // 대화·대기 목록이 바뀌어도 연결 effect 를 다시 돌리지 않는다(재연결 없이 스케줄러에만 전달).
  const viewRef = useRef({ threadId, deliveryRefreshIds });
  const deliveryRef = useRef<DeliveryRefresher | null>(null);

  useEffect(() => {
    viewRef.current = { threadId, deliveryRefreshIds };
    deliveryRef.current?.setView(threadId, deliveryRefreshIds);
  }, [threadId, deliveryRefreshIds]);

  useEffect(() => {
    if (typeof window === 'undefined' || !('EventSource' in window)) return;

    const view = viewRef.current;
    const delivery = createDeliveryRefresher(
      () => router.refresh(),
      view.threadId,
      view.deliveryRefreshIds,
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

      const source = es;
      let opened = false;
      const isCurrent = () => !cancelled && es === source;
      source.addEventListener('message.new', () => { if (isCurrent()) router.refresh(); });
      source.addEventListener('thread.updated', () => { if (isCurrent()) delivery.onUpdate(); });
      source.addEventListener('open', () => {
        if (!isCurrent() || opened) return;
        opened = true;
        attempts = 0;
        delivery.onConnect();
      });
      source.addEventListener('error', () => {
        if (!isCurrent()) return;
        source.close();
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
