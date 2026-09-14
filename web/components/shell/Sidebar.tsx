'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { Route } from 'next';
import { Icon, type IconName } from '@/components/ui';
import { cn } from '@/lib/cn';
import type { SessionUser } from '@/lib/auth';

type NavItem = {
  href: Route;
  label: string;
  icon: IconName;
  count?: number;
  alert?: boolean;
  /** admin 역할만 노출. 비admin이 클릭 시 백엔드 403 → 크래시하던 링크 보호. */
  adminOnly?: boolean;
};

type NavGroup = {
  label: string;
  items: ReadonlyArray<NavItem>;
};

export type SidebarProps = {
  user: SessionUser;
};

// count/alert는 Phase 8+에서 실제 unread 수를 주입하는 구조가 마련되면 복원.
// 지금은 하드코딩 제거 — 사용자 혼란 방지.
const GROUPS: ReadonlyArray<NavGroup> = [
  {
    label: 'Send',
    items: [
      { href: '/', label: '홈', icon: 'home' },
      { href: '/send/new', label: '새 발송', icon: 'send' },
      { href: '/campaigns', label: '발송 이력', icon: 'clock' },
      { href: '/chat', label: '대화방', icon: 'chat' },
    ],
  },
  {
    label: 'People',
    items: [
      { href: '/contacts', label: '주소록', icon: 'users' },
      { href: '/groups', label: '그룹', icon: 'user2' },
    ],
  },
  {
    label: 'Analytics',
    items: [
      { href: '/reports', label: '리포트', icon: 'barChart' },
      { href: '/notifications', label: '알림', icon: 'bell' },
    ],
  },
  {
    label: 'Admin',
    items: [
      // 발신번호 조회는 viewer/sender 도 허용(백엔드 numbers.py = require_user).
      // 등록/삭제 등 관리만 admin 이라 링크 자체는 전원 노출한다.
      { href: '/numbers', label: '발신번호', icon: 'phone' },
      // 설정·감사 로그는 백엔드 라우터가 require_role("admin") 전용.
      // 비admin에게 노출하면 클릭 시 403 → 서버 렌더 크래시하므로 adminOnly.
      // optional catch-all [[...tab]]은 typed routes가 구체 URL 리터럴을
      // 자동 생성하지 않음. /settings 진입 시 server에서 /settings/org로 redirect.
      { href: '/settings' as Route, label: '설정', icon: 'settings', adminOnly: true },
      { href: '/audit', label: '감사 로그', icon: 'fileText', adminOnly: true },
    ],
  },
];

function isActive(pathname: string, href: string) {
  if (href === '/') return pathname === '/';
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function Sidebar({ user }: SidebarProps) {
  const pathname = usePathname();
  const initial = (user.display || user.name || user.email || 'U')
    .trim()
    .charAt(0)
    .toUpperCase();
  const isAdmin = user.roles.includes('admin');
  const org = isAdmin ? 'RAVNUS · admin' : 'RAVNUS';

  return (
    <aside className="k-side" aria-label="주 메뉴">
      <div className="k-brand">
        <div className="k-brand-dot">K</div>
        Kotify
      </div>

      <nav aria-label="네비게이션" className="flex flex-col">
        {GROUPS.map((g) => {
          // adminOnly 항목은 admin 에게만. 필터 후 남는 항목이 없으면 그룹 숨김.
          const items = g.items.filter((item) => !item.adminOnly || isAdmin);
          if (items.length === 0) return null;
          return (
          <div key={g.label}>
            <div className="k-nav-group">{g.label}</div>
            {items.map((item) => {
              const active = isActive(pathname, item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? 'page' : undefined}
                  className={cn('k-nav-item', active && 'on')}
                >
                  <span className="flex items-center gap-2">
                    <Icon name={item.icon} size={14} strokeWidth={1.7} />
                    {item.label}
                  </span>
                  {item.count != null && (
                    <span
                      className={cn('count', item.alert && 'alert')}
                      aria-label={`읽지 않음 ${item.count}개`}
                    >
                      {item.count}
                    </span>
                  )}
                </Link>
              );
            })}
          </div>
          );
        })}
      </nav>

      <div className="k-user">
        <div className="k-user-avatar">{initial}</div>
        <div className="min-w-0">
          <div className="k-user-name truncate">{user.display || user.name}</div>
          <div className="k-user-org truncate">{org}</div>
        </div>
      </div>
    </aside>
  );
}
