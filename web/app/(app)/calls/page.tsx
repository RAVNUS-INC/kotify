import Link from 'next/link';
import type { Route } from 'next';
import { PageHeader } from '@/components/shell';
import { CallsTable, PbxUnavailable, pbxErrorMessage } from '@/components/pbx';
import { Button, EmptyState, Icon } from '@/components/ui';
import { ADMIN_ROLES, hasAnyRole } from '@/lib/access';
import { getSession } from '@/lib/auth';
import { fetchCalls, type CallQuery } from '@/lib/pbx';
import { formatPhone } from '@/lib/phone';

type PageProps = {
  searchParams?: { phone?: string; from?: string; to?: string; type?: string; cursor?: string };
};

const TYPES = ['in', 'out', 'internal', 'transit'] as const;
const PAGE_SIZE = 50;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

function readQuery(sp: PageProps['searchParams']): CallQuery {
  const phone = (sp?.phone ?? '').replace(/\D/g, '');
  const type = TYPES.find((t) => t === sp?.type);
  const cursor = sp?.cursor && /^\d+:[\d.]*$/.test(sp.cursor) ? sp.cursor : undefined;
  return {
    phone: phone || undefined,
    from: sp?.from && DATE.test(sp.from) ? sp.from : undefined,
    to: sp?.to && DATE.test(sp.to) ? sp.to : undefined,
    type,
    limit: PAGE_SIZE,
    cursor,
  };
}

function pageHref(query: CallQuery, cursor?: string): Route {
  const qs = new URLSearchParams();
  if (query.phone) qs.set('phone', query.phone);
  if (query.from) qs.set('from', query.from);
  if (query.to) qs.set('to', query.to);
  if (query.type) qs.set('type', query.type);
  if (cursor) qs.set('cursor', cursor);
  return `/calls${qs.size ? `?${qs.toString()}` : ''}` as Route;
}

export default async function CallsPage({ searchParams }: PageProps) {
  const query = readQuery(searchParams);
  const session = await getSession();
  const isAdmin = session ? hasAnyRole(session.roles, ADMIN_ROLES) : false;
  // 번호 없는 전체 조회는 관리자만 — 백엔드 GET /pbx/calls 와 같은 조건.
  const canQuery = Boolean(query.phone) || isAdmin;

  let body: React.ReactNode;
  let sub = query.phone ? `${formatPhone(query.phone)} 통화 기록` : '전체 통화 기록';
  if (!canQuery) {
    sub = '고객 번호로 통화 기록을 찾습니다';
    body = (
      <div className="rounded-lg border border-line bg-surface">
        <EmptyState icon="search" title="번호를 입력하세요" description="고객 번호를 입력하면 최근 통화와 녹음을 볼 수 있습니다." size="md" />
      </div>
    );
  } else {
    try {
      const res = await fetchCalls(query);
      const name = query.phone ? res.data.find((c) => c.name)?.name : null;
      if (name && query.phone) sub = `${name} · ${formatPhone(query.phone)} 통화 기록`;
      sub = `${sub} · ${res.meta.from} ~ ${res.meta.to}`;
      // PBX 가 offset 을 지원하지 않아 앞쪽으로만 넘긴다(처음으로 = 커서 없이).
      body = (
        <>
          <CallsTable calls={res.data} />
          {query.cursor || res.meta.nextCursor ? (
            <nav aria-label="페이지" className="mt-3 flex justify-end gap-3">
              {query.cursor ? (
                <Link href={pageHref(query)} className="text-sm text-ink-muted hover:text-ink">
                  ← 처음으로
                </Link>
              ) : null}
              {res.meta.nextCursor ? (
                <Link href={pageHref(query, res.meta.nextCursor)} className="text-sm text-ink-muted hover:text-ink">
                  더 이전 통화 →
                </Link>
              ) : null}
            </nav>
          ) : null}
        </>
      );
    } catch (err) {
      body = <PbxUnavailable message={pbxErrorMessage(err)} />;
    }
  }

  return (
    <div className="k-page">
      <PageHeader title="통화 기록" sub={sub} />
      <form
        action="/calls"
        method="get"
        aria-label="통화 기록 조건"
        className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border border-line bg-surface p-4"
      >
        <label className="flex flex-col gap-1 text-sm text-ink-muted">
          고객 번호
          <input
            name="phone"
            defaultValue={query.phone ? formatPhone(query.phone) : ''}
            placeholder="010-0000-0000"
            inputMode="tel"
            className="k-input w-[180px]"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm text-ink-muted">
          시작일
          <input type="date" name="from" defaultValue={query.from ?? ''} className="k-input" />
        </label>
        <label className="flex flex-col gap-1 text-sm text-ink-muted">
          종료일
          <input type="date" name="to" defaultValue={query.to ?? ''} className="k-input" />
        </label>
        <label className="flex flex-col gap-1 text-sm text-ink-muted">
          구분
          <select name="type" defaultValue={query.type ?? ''} className="k-input">
            <option value="">전체</option>
            <option value="in">수신</option>
            <option value="out">발신</option>
            <option value="internal">내선</option>
            <option value="transit">경유</option>
          </select>
        </label>
        <Button type="submit" variant="secondary" size="md" icon={<Icon name="search" size={12} />}>
          조회
        </Button>
        <p className="w-full text-[12px] text-ink-dim">기간을 비우면 최근 30일입니다. 녹음 재생은 감사 로그에 남습니다.</p>
      </form>
      {body}
    </div>
  );
}
