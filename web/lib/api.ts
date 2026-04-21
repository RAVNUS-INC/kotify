/**
 * Server-side envelope fetch helper.
 *
 * Next.js rewrite(/api/:path* → ${FASTAPI_URL}/:path*)는 브라우저 요청에만
 * 적용된다. Server Component에서는 rewrite가 적용되지 않으므로 절대 URL로
 * 직접 호출해야 한다. 이 함수는 server-side 전용.
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

const FASTAPI_URL = process.env.FASTAPI_URL ?? 'http://localhost:8000';

/**
 * FastAPI에 절대 URL로 fetch. envelope `{ data, error }`를 파싱해 `data`만
 * 반환. 에러 시 `ApiError` throw.
 */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const url = path.startsWith('http') ? path : `${FASTAPI_URL}${path}`;
  const res = await fetch(url, {
    cache: 'no-store',
    ...init,
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
    throw new ApiError(res.status, err.code, err.message, err.fields);
  }

  if (body.data === undefined) {
    throw new ApiError(res.status, 'missing_data', 'API 응답에 data가 없습니다');
  }

  return body.data;
}
