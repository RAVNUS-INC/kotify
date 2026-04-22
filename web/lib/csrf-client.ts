/**
 * Client-side CSRF 토큰 + mutating fetch 헬퍼.
 *
 * 서버는 `/api/auth/me` 응답에 `csrfToken` 을 포함한다. 이 모듈은:
 *   1) 최초 호출 시 /me 를 한 번 불러서 토큰을 확보
 *   2) 모듈 단위 메모리에 캐시 (세션당 유효)
 *   3) `apiSend(url, init)` 으로 POST/PATCH/DELETE 시 X-CSRF-Token 자동 첨부
 *
 * 403 (CSRF 검증 실패) 응답을 받으면 캐시를 invalidate 하고 1회 재시도 — 세션이
 * 만료된 후 재로그인 직후 stale 토큰이 남은 케이스를 처리.
 */

let cached: string | null = null;
let inflight: Promise<string> | null = null;

type MeResponse = {
  data?: {
    user?: unknown;
    csrfToken?: string;
  };
  error?: { code: string; message: string };
};

type SetupStatusResponse = {
  data?: {
    completed?: boolean;
    csrfToken?: string;
  };
  error?: { code: string; message: string };
};

async function fetchToken(): Promise<string> {
  // 1) 인증된 사용자 — /auth/me 에서 토큰 회수.
  const res = await fetch('/api/auth/me', { cache: 'no-store' });
  const body = (await res.json()) as MeResponse;
  if (res.ok && !body.error) {
    const token = body.data?.csrfToken ?? '';
    if (token) {
      cached = token;
      return token;
    }
  }

  // 2) 비로그인 상태(401) 또는 토큰 누락 — setup wizard 경로.
  //    /setup/status 는 공용 엔드포인트로 csrf_token 을 내려준다.
  if (res.status === 401) {
    const setupRes = await fetch('/api/setup/status', { cache: 'no-store' });
    const setupBody = (await setupRes.json()) as SetupStatusResponse;
    if (setupRes.ok && !setupBody.error) {
      const setupToken = setupBody.data?.csrfToken ?? '';
      if (setupToken) {
        cached = setupToken;
        return setupToken;
      }
    }
  }

  // 3) 어느 쪽에서도 못 얻으면 의미 있는 에러.
  throw new Error(
    body.error?.message ?? `CSRF 토큰을 가져올 수 없습니다 (HTTP ${res.status})`,
  );
}

/**
 * 토큰을 얻는다. 동시 호출 시 중복 fetch 방지.
 */
export async function getCsrfToken(): Promise<string> {
  if (cached) return cached;
  if (inflight) return inflight;
  inflight = fetchToken().finally(() => {
    inflight = null;
  });
  return inflight;
}

/**
 * 캐시 무효화 — 로그아웃 / 403 받은 경우 호출.
 */
export function invalidateCsrfToken(): void {
  cached = null;
}

/**
 * mutating (POST/PATCH/DELETE/PUT) 용 fetch. X-CSRF-Token 자동 첨부.
 * 403 이면 캐시 재발급 후 1회 재시도.
 */
export async function apiSend(
  input: string,
  init: RequestInit = {},
): Promise<Response> {
  const method = (init.method ?? 'POST').toUpperCase();
  const doFetch = async (): Promise<Response> => {
    const token = await getCsrfToken();
    const headers = new Headers(init.headers ?? {});
    headers.set('X-CSRF-Token', token);
    return fetch(input, { ...init, method, headers });
  };

  let res = await doFetch();
  if (res.status === 403) {
    // 토큰이 stale 이었을 가능성 — 새로 받고 1회 재시도.
    invalidateCsrfToken();
    res = await doFetch();
  }
  return res;
}
