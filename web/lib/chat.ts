import { apiFetch } from './api';
import type { ChatMessage, ChatThread, ChatThreadDetail } from '@/types/chat';

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
 * Client-side fetch. Next rewrite(/api/* → FastAPI)를 경유하므로 상대 경로.
 */
export async function sendMessageClient(
  id: string,
  text: string,
): Promise<ChatMessage> {
  const res = await fetch(
    `/api/threads/${encodeURIComponent(id)}/messages`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
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
  await fetch(`/api/threads/${encodeURIComponent(id)}/read`, {
    method: 'POST',
  });
}
