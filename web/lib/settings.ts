import { apiFetch } from './api';
import { apiSend } from './csrf-client';
import type {
  ApiKey,
  Member,
  Org,
  Webhook,
  WebhookListMeta,
} from '@/types/settings';

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
    msghubWebhookToken: ProviderSecretInfo;
  };
};

export type ProviderPatchInput = Partial<
  ProviderPublicFields & {
    keycloakClientSecret: string;
    msghubApiKey: string;
    msghubApiPwd: string;
    sessionSecret: string;
    msghubWebhookToken: string;
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

export type WebhookListResult = {
  webhooks: Webhook[];
  meta: WebhookListMeta;
};

/**
 * meta(힌트·아웃바운드 미구현 안내)까지 같이 받는 버전. 서버 응답 envelope
 * 에서 data + meta 를 동시에 파싱하려면 apiFetch 대신 fetch 를 직접.
 */
export async function fetchWebhooksWithMeta(): Promise<WebhookListResult> {
  const FASTAPI_URL = process.env.FASTAPI_URL ?? 'http://127.0.0.1:8080';
  // Server component 에서 호출 — cookies 수동 forward (lib/api.ts 와 동일 패턴).
  let cookieHeader = '';
  try {
    const { cookies } = await import('next/headers');
    const all = cookies().getAll();
    cookieHeader = all.map((c) => `${c.name}=${c.value}`).join('; ');
  } catch (err) {
    if (
      err &&
      typeof err === 'object' &&
      'digest' in err &&
      typeof (err as { digest?: unknown }).digest === 'string' &&
      (err as { digest: string }).digest.startsWith('DYNAMIC_SERVER_USAGE')
    ) {
      throw err;
    }
  }
  const res = await fetch(`${FASTAPI_URL}/webhooks`, {
    cache: 'no-store',
    headers: cookieHeader ? { cookie: cookieHeader } : undefined,
  });
  const body = (await res.json()) as {
    data?: Webhook[];
    meta?: WebhookListMeta;
    error?: { code: string; message: string };
  };
  if (!res.ok || body.error || !body.data) {
    throw new Error(body.error?.message ?? `HTTP ${res.status}`);
  }
  return {
    webhooks: body.data,
    meta: body.meta ?? { total: body.data.length },
  };
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

// ── 시스템 업데이트 (git pull + rebuild + 재시작) ──────────────────────────

export type UpdateCheckResult = {
  updateAvailable: boolean;
  current: string;
  remote: string;
  count: number;
  commits: Array<{ hash: string; message: string }>;
};

export async function checkSystemUpdate(): Promise<UpdateCheckResult> {
  // GET 이지만 쿠키 필요 — apiSend 로 통일 (method 명시 없으면 POST 이므로 GET 명시).
  const res = await fetch('/api/system/update/check', { cache: 'no-store' });
  const body = (await res.json()) as {
    data?: UpdateCheckResult;
    error?: { code: string; message: string };
  };
  if (!res.ok || body.error) {
    throw new Error(body.error?.message ?? `HTTP ${res.status}`);
  }
  if (!body.data) throw new Error('API 응답에 data가 없습니다');
  return body.data;
}

export async function applySystemUpdate(): Promise<{
  status: 'ok';
  version: string;
}> {
  const res = await apiSend('/api/system/update/apply', { method: 'POST' });
  const body = (await res.json()) as {
    data?: { status: 'ok'; version: string };
    error?: { code: string; message: string };
  };
  if (!res.ok || body.error) {
    throw new Error(body.error?.message ?? `HTTP ${res.status}`);
  }
  if (!body.data) throw new Error('API 응답에 data가 없습니다');
  return body.data;
}

/**
 * /healthz 를 polling 하여 서버 버전이 target 과 일치하는지 감시.
 * target 이 '?' 면 prev 와 달라지는 순간을 완료로 본다.
 */
export async function waitForVersion(
  target: string,
  prev: string | null,
  options: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<string> {
  const interval = options.intervalMs ?? 1000;
  const timeout = options.timeoutMs ?? 60_000;
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      const res = await fetch('/api/healthz', { cache: 'no-store' });
      if (res.ok) {
        const j = (await res.json()) as { version?: string };
        const v = j.version ?? '';
        const done =
          target !== '?'
            ? v === target
            : prev !== null && v !== '' && v !== prev;
        if (done) return v;
      }
    } catch {
      // 재시작 중 fetch 실패는 정상 — 다음 tick 재시도.
    }
    await new Promise((r) => setTimeout(r, interval));
  }
  throw new Error('재시작 대기 시간 초과');
}

export async function fetchCurrentVersion(): Promise<string | null> {
  try {
    const res = await fetch('/api/healthz', { cache: 'no-store' });
    if (!res.ok) return null;
    const j = (await res.json()) as { version?: string };
    return j.version ?? null;
  } catch {
    return null;
  }
}
