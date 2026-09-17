import { apiFetch } from './api';
import { apiSend } from './csrf-client';
import type {
  ChatMessage,
  ChatThread,
  ChatThreadDetail,
  SendChannel,
} from '@/types/chat';

export type FetchThreadsParams = {
  q?: string;
  unread?: boolean;
};

export async function fetchThreads(
  params: FetchThreadsParams = {},
): Promise<ChatThread[]> {
  const qs = new URLSearchParams();
  if (params.q) qs.set('q', params.q);
  if (params.unread) qs.set('unread', 'true');
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<ChatThread[]>(`/threads${suffix}`);
}

export async function fetchThread(id: string): Promise<ChatThreadDetail> {
  return apiFetch<ChatThreadDetail>(`/threads/${encodeURIComponent(id)}`);
}

/**
 * 결과 리포트를 기다리는(전달 대기) 발신 메시지 id. 대화방 실시간 갱신(ChatLiveRefresh)이
 * 전달 상태 이벤트에 새로고침할지 가르는 기준 — 대기 메시지가 없으면 바뀔 게 없다.
 */
export function getPendingDeliveryIds(
  thread: ChatThreadDetail | null | undefined,
): string[] {
  if (!thread) return [];
  return thread.messages
    .filter((m) => m.side === 'us' && m.status === 'pending')
    .map((m) => m.id);
}

/**
 * Client-side fetch. Next rewrite(/api/* → FastAPI)를 경유하므로 상대 경로.
 */
export async function sendMessageClient(
  id: string,
  text: string,
  sendChannel: SendChannel,
): Promise<ChatMessage> {
  const res = await apiSend(
    `/api/threads/${encodeURIComponent(id)}/messages`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, sendChannel }),
    },
  );
  const body = (await res.json()) as {
    data?: { message: ChatMessage };
    error?: { code: string; message: string };
  };
  if (!res.ok || body.error) {
    throw new Error(body.error?.message ?? `HTTP ${res.status}`);
  }
  if (!body.data) throw new Error('API 응답에 data가 없습니다');
  return body.data.message;
}

export async function markReadClient(id: string): Promise<void> {
  await apiSend(`/api/threads/${encodeURIComponent(id)}/read`, {
    method: 'POST',
  });
}
