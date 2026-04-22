/**
 * Server-side envelope fetch helper.
 *
 * Next.js rewrite(/api/:path* → ${FASTAPI_URL}/:path*)는 브라우저 요청에만
 * 적용된다. Server Component에서는 rewrite가 적용되지 않으므로 절대 URL로
 * 직접 호출해야 한다. 이 함수는 server-side 전용.
 *
 * ⚠️  중요: Next.js 서버 컴포넌트에서 외부 fetch 호출은 **브라우저의
 * Cookie 를 자동으로 forward 하지 않는다**. FastAPI 가 세션을 인식하려면
 * `next/headers.cookies()` 에서 현재 요청의 쿠키를 읽어 `Cookie` 헤더로
 * 직접 전달해야 한다. 이 모듈은 client component에서도 import될 수 있으니
 * `next/headers` 는 **함수 내부에서 동적 import**해 클라이언트 번들에
 * 포함되지 않도록 한다.
 *
 * Client component에서는 상대 경로 `/api/...`로 fetch하면 된다 (rewrite 탐).
 */

export type ApiEnvelope<T> = {
  data?: T;
  meta?: { cursor?: string; total?: number };
  error?: {
    code: string;
    message: string;
    fields?: Record<string, string>;
  };
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields?: Record<string, string>;

  constructor(
    status: number,
    code: string,
    message: string,
    fields?: Record<string, string>,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

const FASTAPI_URL = process.env.FASTAPI_URL ?? 'http://127.0.0.1:8080';

/**
 * FastAPI에 절대 URL로 fetch. envelope `{ data, error }`를 파싱해 `data`만
 * 반환. 에러 시 `ApiError` throw.
 */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const url = path.startsWith('http') ? path : `${FASTAPI_URL}${path}`;

  // 서버 컴포넌트의 요청 쿠키를 FastAPI 로 forward. 이거 없으면 FastAPI 가
  // 세션 인식 못 해서 보호 엔드포인트가 303 을 반환 → 페이지 렌더 실패.
  // 동적 import로 `next/headers`가 **클라이언트 번들에 포함되지 않게** 한다.
  // (webpack 은 `await import()` 를 코드 스플리팅 지점으로 처리해 client bundle
  //  에서 제외. 이 함수는 server component 에서만 호출되므로 런타임엔 항상
  //  `next/headers` 가 가능한 환경이다.)
  // 명시적 `.getAll() → name=value 조합` 방식. `.toString()` 은 일부 Next.js
  // 버전에서 `[object Object]` 반환 버그 사례가 있어 불안정.
  let cookieHeader = '';
  try {
    const { cookies } = await import('next/headers');
    const all = cookies().getAll();
    cookieHeader = all.map((c) => `${c.name}=${c.value}`).join('; ');
  } catch (err) {
    // next/headers 호출 불가 (test 환경 등) — cookie 없이 진행. 단,
    // 프로덕션에서 이 경로로 빠지면 FastAPI 세션 인식 못 해 303 이 됨.
    if (process.env.NODE_ENV === 'production') {
      // eslint-disable-next-line no-console
      console.warn('[apiFetch] cookies() 접근 실패 — 세션 전달 불가', err);
    }
  }

  const res = await fetch(url, {
    cache: 'no-store',
    ...init,
    headers: {
      ...(cookieHeader ? { cookie: cookieHeader } : {}),
      ...(init?.headers ?? {}),
    },
  });

  let body: ApiEnvelope<T>;
  try {
    body = (await res.json()) as ApiEnvelope<T>;
  } catch {
    throw new ApiError(
      res.status,
      'invalid_json',
      `API 응답 파싱 실패 (${res.status})`,
    );
  }

  if (!res.ok || body.error) {
    const err = body.error ?? { code: 'http_error', message: `HTTP ${res.status}` };
    // 진단: 인증 계열 실패는 쿠키 forward 정황을 확인할 수 있도록 로깅.
    if (process.env.NODE_ENV === 'production' && (res.status === 401 || res.status === 303)) {
      // eslint-disable-next-line no-console
      console.warn(
        `[apiFetch] ${res.status} on ${path} — cookie 길이=${cookieHeader.length}, keys=[${
          cookieHeader
            .split(';')
            .map((c) => c.trim().split('=')[0])
            .filter(Boolean)
            .join(',')
        }]`,
      );
    }
    throw new ApiError(res.status, err.code, err.message, err.fields);
  }

  if (body.data === undefined) {
    throw new ApiError(res.status, 'missing_data', 'API 응답에 data가 없습니다');
  }

  return body.data;
}
