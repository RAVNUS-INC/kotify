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
      { href: '/numbers', label: '발신번호', icon: 'phone' },
      { href: '/settings', label: '설정', icon: 'settings' },
      { href: '/audit', label: '감사 로그', icon: 'fileText' },
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
  const org = user.roles.includes('admin') ? 'RAVNUS · admin' : 'RAVNUS';

  return (
    <aside className="k-side" aria-label="주 메뉴">
      <div className="k-brand">
        <div className="k-brand-dot">K</div>
        Kotify
      </div>

      <nav aria-label="네비게이션" className="flex flex-col">
        {GROUPS.map((g) => (
          <div key={g.label}>
            <div className="k-nav-group">{g.label}</div>
            {g.items.map((item) => {
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
        ))}
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
