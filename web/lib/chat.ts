import { apiFetch } from './api';
import type { ChatThread, ChatThreadDetail } from '@/types/chat';

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
