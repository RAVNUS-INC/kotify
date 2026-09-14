/**
 * API 에러 타입 — 서버(apiFetch)와 클라이언트(error.tsx)가 함께 쓴다.
 * 클라이언트 번들에 서버 fetch 코드가 딸려가지 않도록 lib/api.ts 와 분리.
 */

const API_ERROR_DIGEST_PREFIX = 'KOTIFY_API:';
const API_ERROR_DIGEST_PATTERN = /^KOTIFY_API:(\d{3}):(.+)$/;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields?: Record<string, string>;
  /**
   * 프로덕션에서 Next 는 서버 컴포넌트 에러 메시지를 가리지만, 미리 설정된
   * digest 는 그대로 error.tsx 까지 전달한다. 상태·코드를 실어 error.tsx 가
   * 403·로그인 필요 등을 구분해 안내할 수 있게 한다.
   */
  readonly digest: string;

  constructor(status: number, code: string, message: string, fields?: Record<string, string>) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.fields = fields;
    this.digest = `${API_ERROR_DIGEST_PREFIX}${status}:${code}`;
  }
}

/** ApiError digest 면 상태·코드를, 아니면 null. */
export function parseApiErrorDigest(
  digest: string | undefined,
): { status: number; code: string } | null {
  const match = digest ? API_ERROR_DIGEST_PATTERN.exec(digest) : null;
  if (!match) return null;
  return { status: Number(match[1]), code: match[2] ?? '' };
}
