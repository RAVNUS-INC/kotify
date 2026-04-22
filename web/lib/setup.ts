/**
 * Setup wizard 전용 client lib — fresh install 부트스트랩 플로우.
 *
 * POST 들은 apiSend 로 CSRF 자동 첨부.
 */

import { apiSend } from './csrf-client';

export type SetupStatus = {
  completed: boolean;
  tokenPath: string;
  tokenVerified: boolean;
  csrfToken: string;
};

type Envelope<T> = {
  data?: T;
  error?: { code: string; message: string };
};

async function parse<T>(res: Response): Promise<T> {
  const body = (await res.json()) as Envelope<T>;
  if (!res.ok || body.error) {
    throw new Error(body.error?.message ?? `HTTP ${res.status}`);
  }
  if (body.data === undefined) {
    throw new Error('응답에 data 가 없습니다');
  }
  return body.data;
}

export async function fetchSetupStatus(
  options: { timeoutMs?: number } = {},
): Promise<SetupStatus> {
  const controller = new AbortController();
  const timer = setTimeout(
    () => controller.abort(),
    options.timeoutMs ?? 10_000,
  );
  try {
    const res = await fetch('/api/setup/status', {
      cache: 'no-store',
      signal: controller.signal,
    });
    return parse<SetupStatus>(res);
  } finally {
    clearTimeout(timer);
  }
}

export async function verifySetupToken(token: string): Promise<void> {
  const res = await apiSend('/api/setup/verify-token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  });
  await parse<{ verified: boolean }>(res);
}

export async function testSetupKeycloak(keycloakIssuer: string): Promise<{
  ok: true;
  issuer: string;
}> {
  const res = await apiSend('/api/setup/test-keycloak', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keycloakIssuer }),
  });
  return parse<{ ok: true; issuer: string }>(res);
}

export async function testSetupMsghub(input: {
  msghubApiKey: string;
  msghubApiPwd: string;
  msghubEnv?: string;
}): Promise<{ ok: true; env: string }> {
  const res = await apiSend('/api/setup/test-msghub', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      msghubApiKey: input.msghubApiKey,
      msghubApiPwd: input.msghubApiPwd,
      msghubEnv: input.msghubEnv ?? 'production',
    }),
  });
  return parse<{ ok: true; env: string }>(res);
}

export type CompleteSetupInput = {
  token: string;
  keycloakIssuer: string;
  keycloakClientId: string;
  keycloakClientSecret: string;
  msghubApiKey: string;
  msghubApiPwd: string;
  msghubEnv?: string;
  msghubBrandId?: string;
  msghubChatbotId?: string;
  appPublicUrl?: string;
  firstAdminEmail?: string;
};

export type CompleteSetupResult = {
  completed: true;
  next: string;
  /**
   * true 면 앱 재시작 후 로그인하도록 안내해야 한다.
   * 새로 저장된 session.secret 이 running process 에는 반영 안 되고 다음
   * restart 에 활성화되기 때문 — 재시작 전에 만든 세션은 이후 무효화된다.
   */
  restartRecommended?: boolean;
};

export async function completeSetup(
  input: CompleteSetupInput,
): Promise<CompleteSetupResult> {
  const res = await apiSend('/api/setup/complete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  return parse<CompleteSetupResult>(res);
}
