'use client';

import { Fragment } from 'react';
import Link from 'next/link';
import type { Route } from 'next';
import { usePathname } from 'next/navigation';
import { Icon } from '@/components/ui';
import { CommandPalette } from '@/components/search';

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
  calls: '통화 기록',
  fax: '팩스',
  search: '검색',
  kitchen: 'Kitchen Sink',
};

// 상세 화면의 동적 구간(/chat/<caller:phone> 등)은 내부 키라 그대로 보여주지 않는다.
// 부모 구간 기준으로 사람이 읽는 이름을 붙인다. 화면 제목이 실제 이름·번호를 보여준다.
const DETAIL_LABELS: Record<string, string> = {
  chat: '대화',
  campaigns: '캠페인 상세',
  groups: '그룹 상세',
};

const SETTINGS_TAB_LABELS: Record<string, string> = {
  org: '조직',
  messaging: '메시징',
  developers: '개발자',
  security: '보안',
};

function segmentLabel(seg: string, parent: string | undefined): string {
  if (parent === 'settings' && SETTINGS_TAB_LABELS[seg]) return SETTINGS_TAB_LABELS[seg];
  if (parent && DETAIL_LABELS[parent]) return DETAIL_LABELS[parent];
  if (SEGMENT_LABELS[seg]) return SEGMENT_LABELS[seg];
  try {
    return decodeURIComponent(seg);
  } catch {
    return seg;
  }
}

type Crumb = {
  href: Route;
  label: string;
  /** 해당 경로에 페이지가 없는 중간 구간(/send)은 링크로 만들지 않는다 */
  linkable: boolean;
};

const UNLINKABLE_PATHS = new Set(['/send']);

export function buildCrumbs(pathname: string): Crumb[] {
  const segs = pathname.split('/').filter(Boolean);
  const crumbs: Crumb[] = [{ href: '/' as Route, label: '홈', linkable: true }];
  let acc = '';
  segs.forEach((s, i) => {
    acc += `/${s}`;
    crumbs.push({
      href: acc as Route,
      label: segmentLabel(s, segs[i - 1]),
      linkable: !UNLINKABLE_PATHS.has(acc),
    });
  });
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
                ) : !c.linkable ? (
                  <span className="text-ink-muted">{c.label}</span>
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
        <CommandPalette />
        <Link
          href={'/notifications' as Route}
          className="k-btn k-btn-ghost k-btn-sm relative"
          aria-label="알림센터"
        >
          <Icon name="bell" size={16} />
        </Link>
      </div>
    </div>
  );
}
