'use client';

import { useChatStream } from './useChatStream';

/**
 * 대화방 실시간 갱신 구독기 — UI 를 그리지 않고 SSE 연결만 유지한다.
 *
 * /chat 페이지는 서버 컴포넌트라 훅을 직접 쓸 수 없고, ThreadView 는 대화를
 * 선택했을 때만 렌더되어 목록만 보는 동안엔 구독이 끊긴다. 그래서 항상 렌더되는
 * 이 경량 클라이언트 컴포넌트에 훅을 붙여, 목록/상세 어느 상태에서든 고객 회신이
 * 오면 즉시 화면이 갱신되게 한다.
 */
export function ChatLiveRefresh() {
  useChatStream();
  return null;
}
