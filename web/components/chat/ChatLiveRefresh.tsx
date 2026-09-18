'use client';

import { useChatStream } from './useChatStream';

export type ChatLiveRefreshProps = {
  /** 열린 대화방 id. 목록만 볼 땐 생략. */
  threadId?: string;
  /** 열린 대화방의 대기·실패 발신 메시지 id(lib/chat getDeliveryRefreshIds). 목록만 볼 땐 생략. */
  deliveryRefreshIds?: string[];
};

/**
 * 대화방 실시간 갱신 구독기 — UI 를 그리지 않고 SSE 연결만 유지한다.
 *
 * /chat 페이지는 서버 컴포넌트라 훅을 직접 쓸 수 없고, ThreadView 는 대화를
 * 선택했을 때만 렌더되어 목록만 보는 동안엔 구독이 끊긴다. 그래서 항상 렌더되는
 * 이 경량 클라이언트 컴포넌트에 훅을 붙여, 목록/상세 어느 상태에서든 고객 회신이
 * 오면 새로고침 없이 화면이 갱신되게 한다 — 몰려온 회신은 서버가 5초 창으로 합쳐
 * 알린다. 대화를 골라도 같은 자리라 연결이 유지된다.
 *
 * 탭당 이것 하나만 구독한다 — 예전엔 ThreadView 도 따로 구독해 대화를 연 /chat 에서 이벤트
 * 1건에 새로고침(목록·상세 API 재호출)이 두 번 돌았다. 열린 대화와 그 대화의 전달 대기
 * 메시지는 페이지가 넘겨 주고, 대기·실패 메시지가 있을 때 전달 상태 이벤트에 새로고침한다.
 */
export function ChatLiveRefresh({ threadId, deliveryRefreshIds }: ChatLiveRefreshProps) {
  useChatStream({ threadId, deliveryRefreshIds });
  return null;
}
