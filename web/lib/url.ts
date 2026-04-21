/**
 * URL 안전 헬퍼 — open redirect 방어.
 *
 * 내부 경로(`/foo`)만 허용하고 외부 스킴(`https:`, `//evil.com`,
 * `javascript:`, `data:`)은 전부 차단한다.
 * 로그인 리다이렉트와 알림 href 양쪽에서 공유한다.
 */

const FALLBACK = '/';

/**
 * 임의 입력을 안전한 내부 경로로 정규화한다.
 *
 * 허용:
 * - `/` 로 시작하고
 * - `//` 로 시작하지 않으며
 * - 콜론(`:`) 없이 스킴이 붙지 않은 값
 *
 * 이 외의 모든 경우 `fallback` (기본 `/`) 반환.
 *
 * @example
 *   safeInternalHref('/campaigns')       // → '/campaigns'
 *   safeInternalHref('//evil.com')       // → '/'
 *   safeInternalHref('javascript:alert') // → '/'
 *   safeInternalHref('https://x.com')    // → '/'
 *   safeInternalHref(undefined)          // → '/'
 */
export function safeInternalHref(
  raw: string | null | undefined,
  fallback: string = FALLBACK,
): string {
  if (typeof raw !== 'string' || raw.length === 0) return fallback;
  // 스킴 포함 URL 차단 (javascript:, data:, http: 등)
  if (/^[a-z][a-z0-9+\-.]*:/i.test(raw)) return fallback;
  // protocol-relative 차단
  if (raw.startsWith('//')) return fallback;
  // 내부 경로만 허용
  if (!raw.startsWith('/')) return fallback;
  return raw;
}
