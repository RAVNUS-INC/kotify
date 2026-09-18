import { ApiError, apiFetch, apiFetchEnvelope } from './api';
import { apiSend } from './csrf-client';
import type {
  ChatMessage,
  ChatThread,
  ChatThreadDetail,
  ChatThreadPage,
  ChatThreadPageMeta,
  SendChannel,
} from '@/types/chat';

export type FetchThreadsParams = {
  q?: string;
  unread?: boolean;
  limit?: number;
  offset?: number;
};

function threadsPath(params: FetchThreadsParams): string {
  const qs = new URLSearchParams();
  if (params.q) qs.set('q', params.q);
  if (params.unread) qs.set('unread', 'true');
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  if (params.offset !== undefined) qs.set('offset', String(params.offset));
  return `/threads${qs.size ? `?${qs.toString()}` : ''}`;
}

export async function fetchThreads(
  params: FetchThreadsParams = {},
): Promise<ChatThread[]> {
  return apiFetch<ChatThread[]>(threadsPath(params));
}

export async function fetchThreadPage(params: FetchThreadsParams = {}): Promise<ChatThreadPage> {
  const response = await apiFetchEnvelope<ChatThread[], ChatThreadPageMeta>(threadsPath(params));
  if (!response.meta) throw new ApiError(200, 'missing_meta', '대화 목록의 페이지 정보가 없습니다');
  return { data: response.data, meta: response.meta };
}

export async function fetchThread(id: string): Promise<ChatThreadDetail> {
  return apiFetch<ChatThreadDetail>(`/threads/${encodeURIComponent(id)}`);
}

/**
 * 전달 상태 이벤트로 갱신할 발신 메시지 id. 실패에도 요청 타임아웃처럼 실제 접수 여부를
 * 모르는 건이 섞여 있어, 늦은 리포트·재조정으로 대기/전달 상태가 될 수 있다.
 * 현재 API는 확정 실패와 구분하지 않으므로 대기·실패를 함께 감시한다. 이벤트 없이 폴링하지 않는다.
 */
export function getDeliveryRefreshIds(
  thread: ChatThreadDetail | null | undefined,
): string[] {
  if (!thread) return [];
  return thread.messages
    .filter((m) => m.side === 'us' && (m.status === 'pending' || m.status === 'failed'))
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
    error?: { code: string; message: string; fields?: Record<string, string> };
  };
  if (!res.ok || body.error) {
    throw new ApiError(
      res.status, body.error?.code ?? 'http_error',
      body.error?.message ?? `HTTP ${res.status}`, body.error?.fields,
    );
  }
  if (!body.data) throw new Error('API 응답에 data가 없습니다');
  return body.data.message;
}

export async function markReadClient(id: string, lastReadMessageId: number): Promise<void> {
  const res = await apiSend(`/api/threads/${encodeURIComponent(id)}/read`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lastReadMessageId }),
  });
  if (!res.ok) throw new Error(`읽음 처리 실패 (HTTP ${res.status})`);
}
