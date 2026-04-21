'use client';

import { Fragment } from 'react';
import Link from 'next/link';
import type { Route } from 'next';
import { usePathname } from 'next/navigation';
import { Icon, Kbd } from '@/components/ui';

const SEGMENT_LABELS: Record<string, string> = {
  send: '발송',
  new: '새 발송',
  campaigns: '발송 이력',
  chat: '대화방',
  contacts: '주소록',
  groups: '그룹',
  reports: '리포트',
  notifications: '알림',
  numbers: '발신번호',
  settings: '설정',
  audit: '감사 로그',
  kitchen: 'Kitchen Sink',
};

type Crumb = {
  href: Route;
  label: string;
};

function buildCrumbs(pathname: string): Crumb[] {
  const segs = pathname.split('/').filter(Boolean);
  const crumbs: Crumb[] = [{ href: '/' as Route, label: '홈' }];
  let acc = '';
  for (const s of segs) {
    acc += `/${s}`;
    crumbs.push({
      href: acc as Route,
      label: SEGMENT_LABELS[s] ?? s,
    });
  }
  return crumbs;
}

export function Topbar() {
  const pathname = usePathname();
  const crumbs = buildCrumbs(pathname);
  const last = crumbs.length - 1;

  return (
    <div className="k-topbar">
      <nav aria-label="경로" className="k-crumb">
        <ol className="flex items-center gap-2 p-0 m-0 list-none">
          {crumbs.map((c, i) => (
            <Fragment key={c.href}>
              {i > 0 && (
                <li aria-hidden className="sep">
                  /
                </li>
              )}
              <li>
                {i === last ? (
                  <strong>{c.label}</strong>
                ) : (
                  <Link href={c.href} className="text-ink-muted hover:text-ink">
                    {c.label}
                  </Link>
                )}
              </li>
            </Fragment>
          ))}
        </ol>
      </nav>

      <div className="k-topbar-right">
        <button
          type="button"
          className="k-btn k-btn-ghost k-btn-sm"
          aria-label="검색 (Cmd+K)"
        >
          <Icon name="search" size={13} />
          <Kbd className="ml-1">⌘K</Kbd>
        </button>
        <button
          type="button"
          className="k-btn k-btn-ghost k-btn-sm relative"
          aria-label="알림 (3개 읽지 않음)"
        >
          <Icon name="bell" size={13} />
          <span
            aria-hidden
            className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-brand"
          />
        </button>
      </div>
    </div>
  );
}
