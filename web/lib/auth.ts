import { cookies } from 'next/headers';

export type Role = 'owner' | 'admin' | 'operator' | 'viewer' | string;

export type SessionUser = {
  sub: string;
  email: string;
  name: string;
  display: string;
  roles: ReadonlyArray<Role>;
};

export const SESSION_COOKIE = 'sms_session';

const FASTAPI_URL = process.env.FASTAPI_URL ?? 'http://127.0.0.1:8080';

export function isAuthDisabled(): boolean {
  // production에서는 AUTH_DISABLED 무조건 무시 (실수 방지)
  if (process.env.NODE_ENV === 'production') return false;
  return process.env.AUTH_DISABLED === 'true';
}

const DEV_USER: SessionUser = {
  sub: 'dev-sub',
  email: 'dev@kotify.local',
  name: '김운영',
  display: '김운영',
  roles: ['admin'],
};

/**
 * Server-only. 현재 요청 쿠키로 FastAPI /auth/me를 호출해 세션을 확인한다.
 * AUTH_DISABLED=true 환경에서는 mock user를 반환한다.
 */
export async function getSession(): Promise<SessionUser | null> {
  if (isAuthDisabled()) return DEV_USER;

  const store = cookies();
  const cookie = store.get(SESSION_COOKIE);
  if (!cookie) return null;

  try {
    const res = await fetch(`${FASTAPI_URL}/auth/me`, {
      headers: { cookie: `${SESSION_COOKIE}=${cookie.value}` },
      cache: 'no-store',
    });
    if (!res.ok) return null;
    const body = (await res.json()) as { data?: { user?: SessionUser } };
    return body.data?.user ?? null;
  } catch {
    return null;
  }
}

export function hasRole(user: SessionUser, ...required: Role[]): boolean {
  return required.some((r) => user.roles.includes(r));
}
