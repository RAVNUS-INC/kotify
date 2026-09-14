import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { hasAnyRole, requiredRoles } from '@/lib/access';
import { forbiddenHtml } from '@/lib/forbidden-page';

const SESSION_COOKIE = 'sms_session';
const FASTAPI_URL = process.env.FASTAPI_URL ?? 'http://127.0.0.1:8080';
const SESSION_CHECK_TIMEOUT_MS = 3000;

// 보호하지 않는 경로들 (로그인, 콜백, 정적 자산 등)
const PUBLIC_PATTERNS = [/^\/login/, /^\/onboarding/, /^\/offline/, /^\/fonts/];

type SessionCheck =
  | { status: 'ok'; roles: string[] }
  | { status: 'unauthenticated' }
  | { status: 'unavailable' };

/**
 * FastAPI /auth/me 로 세션과 역할을 확인한다.
 * 401 만 "로그인 필요"로 보고, 그 밖의 실패(백엔드 다운·타임아웃·5xx)는 판단
 * 불가로 돌려준다 — 이때 권한 없음으로 단정하면 admin 에게도 거짓 403 이 뜬다.
 */
async function checkSession(sessionValue: string): Promise<SessionCheck> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), SESSION_CHECK_TIMEOUT_MS);
  try {
    const res = await fetch(`${FASTAPI_URL}/auth/me`, {
      headers: { cookie: `${SESSION_COOKIE}=${sessionValue}` },
      cache: 'no-store',
      signal: controller.signal,
    });
    if (res.status === 401) return { status: 'unauthenticated' };
    if (!res.ok) return { status: 'unavailable' };
    const body = (await res.json()) as { data?: { user?: { roles?: unknown } } };
    const roles = body.data?.user?.roles;
    if (!Array.isArray(roles)) return { status: 'unavailable' };
    return { status: 'ok', roles: roles.map(String) };
  } catch {
    return { status: 'unavailable' };
  } finally {
    clearTimeout(timer);
  }
}

function redirectToLogin(request: NextRequest, pathname: string): NextResponse {
  const url = request.nextUrl.clone();
  url.pathname = '/login';
  url.search = pathname === '/' ? '' : `?from=${encodeURIComponent(pathname)}`;
  return NextResponse.redirect(url);
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // 개발 우회 (production에서는 절대 무시)
  if (
    process.env.NODE_ENV !== 'production' &&
    process.env.AUTH_DISABLED === 'true'
  ) {
    return NextResponse.next();
  }

  // API 프록시는 FastAPI가 인증 처리 (Keycloak redirect 포함)
  if (pathname.startsWith('/api')) return NextResponse.next();

  // 공개 경로
  if (PUBLIC_PATTERNS.some((re) => re.test(pathname))) {
    return NextResponse.next();
  }

  // 세션 쿠키 검사 — 없으면 /login으로
  const session = request.cookies.get(SESSION_COOKIE);
  if (!session) return redirectToLogin(request, pathname);

  // 역할 제한 경로 — 백엔드와 같은 조건으로 먼저 거른다. 미달이면 페이지를
  // 렌더하지 않고 403 안내 HTML 을 본문으로 응답한다 (rewrite 는 상태 코드가
  // 페이지 렌더에 전달되지 않아 200 이 된다).
  const required = requiredRoles(pathname);
  if (!required) return NextResponse.next();

  const check = await checkSession(session.value);
  if (check.status === 'unauthenticated') {
    return redirectToLogin(request, pathname);
  }
  // 판단 불가면 통과 — 페이지의 데이터 fetch 가 실패하면 error.tsx(다시 시도)가 받는다.
  if (check.status === 'unavailable' || hasAnyRole(check.roles, required)) {
    return NextResponse.next();
  }

  return new NextResponse(forbiddenHtml(), {
    status: 403,
    headers: {
      'content-type': 'text/html; charset=utf-8',
      'cache-control': 'no-store',
    },
  });
}

export const config = {
  matcher: [
    // _next/static, _next/image, favicon, public 자산 제외
    '/((?!_next/static|_next/image|favicon.ico|fonts|.*\\..*).*)',
  ],
};
