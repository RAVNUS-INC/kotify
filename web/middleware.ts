import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const SESSION_COOKIE = 'sms_session';

// 보호하지 않는 경로들 (로그인, 콜백, 정적 자산 등)
const PUBLIC_PATTERNS = [/^\/login/, /^\/onboarding/, /^\/offline/, /^\/fonts/];

export function middleware(request: NextRequest) {
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
  if (!session) {
    const url = request.nextUrl.clone();
    url.pathname = '/login';
    url.search = pathname === '/' ? '' : `?from=${encodeURIComponent(pathname)}`;
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    // _next/static, _next/image, favicon, public 자산 제외
    '/((?!_next/static|_next/image|favicon.ico|fonts|.*\\..*).*)',
  ],
};
