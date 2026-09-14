/**
 * 경로별 역할 요구사항 — 프론트 권한 판단의 단일 출처.
 *
 * middleware(서버 게이트, 미달 시 403 페이지)와 Sidebar(링크 노출)가 함께 쓴다.
 * 조건은 백엔드 게이트와 같아야 한다:
 *   /settings → app/routes/settings.py   require_role("admin")
 *   /audit    → app/routes/audit_api.py  require_role("admin")
 *   /send     → POST /campaigns          require_sender (sender/admin/owner)
 *
 * Edge runtime(middleware)에서도 import 되므로 순수 TS 만 둔다.
 */

export const ADMIN_ROLES: ReadonlyArray<string> = ['admin'];
export const SEND_ROLES: ReadonlyArray<string> = ['sender', 'admin', 'owner'];

const ROUTE_ROLES: ReadonlyArray<{
  prefix: string;
  roles: ReadonlyArray<string>;
}> = [
  { prefix: '/settings', roles: ADMIN_ROLES },
  { prefix: '/audit', roles: ADMIN_ROLES },
  { prefix: '/send', roles: SEND_ROLES },
];

function withinPrefix(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

/** 경로에 필요한 역할 목록. 제한 없는 경로면 null. */
export function requiredRoles(pathname: string): ReadonlyArray<string> | null {
  return ROUTE_ROLES.find((r) => withinPrefix(pathname, r.prefix))?.roles ?? null;
}

export function hasAnyRole(roles: ReadonlyArray<string>, allowed: ReadonlyArray<string>): boolean {
  return allowed.some((r) => roles.includes(r));
}

export function canAccessPath(pathname: string, roles: ReadonlyArray<string>): boolean {
  const required = requiredRoles(pathname);
  return required === null || hasAnyRole(roles, required);
}
