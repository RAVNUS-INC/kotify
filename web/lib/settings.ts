import { apiFetch } from './api';
import { apiSend } from './csrf-client';
import type { ApiKey, Member, Org, Webhook } from '@/types/settings';

export type ProviderPublicFields = {
  keycloakIssuer: string;
  keycloakClientId: string;
  appPublicUrl: string;
  msghubEnv: string;
  msghubBrandId: string;
  msghubChatbotId: string;
};

export type ProviderSecretInfo = {
  configured: boolean;
  masked: string;
};

export type ProviderSettings = {
  public: ProviderPublicFields;
  secrets: {
    keycloakClientSecret: ProviderSecretInfo;
    msghubApiKey: ProviderSecretInfo;
    msghubApiPwd: ProviderSecretInfo;
    sessionSecret: ProviderSecretInfo;
  };
};

export type ProviderPatchInput = Partial<
  ProviderPublicFields & {
    keycloakClientSecret: string;
    msghubApiKey: string;
    msghubApiPwd: string;
    sessionSecret: string;
  }
>;

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

/**
 * Server-side fetch — provider (msghub/keycloak/app) 공개 설정 + 시크릿
 * 마스킹 정보. 평문 시크릿은 절대 응답에 포함되지 않는다.
 */
export async function fetchProviderSettings(): Promise<ProviderSettings> {
  return apiFetch<ProviderSettings>('/settings/provider');
}

/**
 * Client-side PATCH — provider 설정 일부 업데이트.
 * 빈 시크릿 값은 기존 값 보존. msghub.* 변경 시 서버가 자동으로 클라이언트
 * 재초기화.
 */
export async function patchProviderClient(
  updates: ProviderPatchInput,
): Promise<ProviderSettings> {
  const res = await apiSend('/api/settings/provider', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  const body = (await res.json()) as {
    data?: ProviderSettings;
    error?: { code: string; message: string };
  };
  if (!res.ok || body.error) {
    throw new Error(body.error?.message ?? `HTTP ${res.status}`);
  }
  if (!body.data) throw new Error('API 응답에 data가 없습니다');
  return body.data;
}

/**
 * msghub 인증 테스트 — 현재 저장된 키로 외부 msghub API 호출.
 * 422 (not_configured/auth_failed), 502 (connect_failed), 503 (module unavailable)
 * 의 각 에러 케이스를 메시지 그대로 던진다.
 */
export async function testMsghubClient(): Promise<{
  ok: true;
  message: string;
  env: string;
}> {
  const res = await apiSend('/api/settings/test-msghub', { method: 'POST' });
  const body = (await res.json()) as {
    data?: { ok: true; message: string; env: string };
    error?: { code: string; message: string };
  };
  if (!res.ok || body.error) {
    throw new Error(body.error?.message ?? `HTTP ${res.status}`);
  }
  if (!body.data) throw new Error('API 응답에 data가 없습니다');
  return body.data;
}
