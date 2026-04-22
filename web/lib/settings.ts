import { apiFetch } from './api';
import { apiSend } from './csrf-client';
import type { ApiKey, Member, Org, Webhook } from '@/types/settings';

export async function fetchOrg(): Promise<Org> {
  return apiFetch<Org>('/org');
}

export async function fetchMembers(): Promise<Member[]> {
  return apiFetch<Member[]>('/members');
}

export async function fetchApiKeys(): Promise<ApiKey[]> {
  return apiFetch<ApiKey[]>('/api-keys');
}

export async function fetchWebhooks(): Promise<Webhook[]> {
  return apiFetch<Webhook[]>('/webhooks');
}

/**
 * Client-side PATCH /org. envelope error 시 throw.
 *
 * 주의: 이 함수는 client component에서만 호출한다. 상대 경로 `/api/org`는
 * Next.js rewrite가 FastAPI `/org`로 프록시한다 (next.config.mjs).
 * Server Component에서는 apiFetch()로 절대 URL 직접 호출 (fetchOrg 참고).
 */
export async function patchOrgClient(
  updates: Partial<Pick<Org, 'name' | 'service' | 'contact' | 'timezone'>>,
): Promise<Org> {
  const res = await apiSend('/api/org', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  const body = (await res.json()) as {
    data?: Org;
    error?: { code: string; message: string };
  };
  if (!res.ok || body.error) {
    throw new Error(body.error?.message ?? `HTTP ${res.status}`);
  }
  if (!body.data) throw new Error('API 응답에 data가 없습니다');
  return body.data;
}
