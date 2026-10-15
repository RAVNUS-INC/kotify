/**
 * Server-side PBX 조회 — 팩스 이력, 통화 기록.
 * 브라우저는 녹음 원본 주소를 받지 않는다. 재생은 `/api/pbx/recordings/{token}` 만 쓴다.
 */
import { apiFetchEnvelope, ApiError } from './api';
import type { CallListMeta, CallRecord, FaxJob, FaxListMeta } from '@/types/pbx';

export async function fetchFaxJobs(params: {
  limit?: number;
  offset?: number;
}): Promise<{ data: FaxJob[]; meta: FaxListMeta }> {
  const qs = new URLSearchParams();
  if (params.limit) qs.set('limit', String(params.limit));
  if (params.offset) qs.set('offset', String(params.offset));
  const res = await apiFetchEnvelope<FaxJob[], FaxListMeta>(`/fax?${qs.toString()}`);
  return {
    data: res.data,
    meta: res.meta ?? { limit: params.limit ?? 50, offset: params.offset ?? 0, hasMore: false },
  };
}

export type CallQuery = {
  phone?: string;
  from?: string;
  to?: string;
  type?: 'in' | 'out' | 'internal' | 'transit';
  limit?: number;
  offset?: number;
};

export async function fetchCalls(
  query: CallQuery,
): Promise<{ data: CallRecord[]; meta: CallListMeta }> {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== '') qs.set(key, String(value));
  }
  const res = await apiFetchEnvelope<CallRecord[], CallListMeta>(`/pbx/calls?${qs.toString()}`);
  return {
    data: res.data,
    meta: res.meta ?? {
      limit: query.limit ?? 50,
      offset: query.offset ?? 0,
      hasMore: false,
      from: query.from ?? '',
      to: query.to ?? '',
    },
  };
}

export type RecentCallsResult =
  | { status: 'ok'; calls: CallRecord[] }
  | { status: 'unavailable' };

/**
 * 대화방 오른쪽 카드용 최근 통화. PBX 미설정·장애·권한 없음은 모두 `unavailable` 로
 * 격리한다 — 통화 기록이 없어도 대화방은 그대로 동작해야 한다.
 */
export async function fetchRecentCalls(phone: string, limit = 5): Promise<RecentCallsResult> {
  try {
    const res = await fetchCalls({ phone, limit });
    return { status: 'ok', calls: res.data };
  } catch (err) {
    if (err instanceof ApiError) return { status: 'unavailable' };
    throw err;
  }
}
