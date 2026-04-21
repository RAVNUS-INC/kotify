import Link from 'next/link';
import type { Route } from 'next';
import type { Contact } from '@/types/contact';
import { Badge, EmptyState, Pill } from '@/components/ui';
import { cn } from '@/lib/cn';

export type ContactsTableProps = {
  contacts: ReadonlyArray<Contact>;
  selectedId?: string;
  filter?: { q?: string };
};

function buildHref(id: string, filter?: { q?: string }): Route {
  const qs = new URLSearchParams();
  qs.set('selected', id);
  if (filter?.q) qs.set('q', filter.q);
  return `/contacts?${qs.toString()}` as Route;
}

export function ContactsTable({ contacts, selectedId, filter }: ContactsTableProps) {
  if (contacts.length === 0) {
    return (
      <div className="rounded-lg border border-line bg-surface">
        <EmptyState
          icon="users"
          title="연락처 없음"
          description="검색 조건에 맞는 연락처가 없습니다."
          size="md"
        />
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface">
      <div className="overflow-x-auto">
        <table className="k-tbl">
          <thead>
            <tr>
              <th>이름</th>
              <th>번호</th>
              <th>이메일</th>
              <th>팀</th>
              <th>태그</th>
              <th>최근 캠페인</th>
            </tr>
          </thead>
          <tbody>
            {contacts.map((c) => {
              const isActive = c.id === selectedId;
              return (
                <tr
                  key={c.id}
                  className={cn(isActive && 'bg-brand-soft')}
                >
                  <td>
                    <Link
                      href={buildHref(c.id, filter)}
                      className="flex items-center gap-2 font-medium text-ink hover:text-brand"
                      aria-current={isActive ? 'true' : undefined}
                    >
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gray-3 font-mono text-[11px] text-gray-9">
                        {c.name.charAt(0)}
                      </span>
                      <span className="truncate">{c.name}</span>
                    </Link>
                  </td>
                  <td className="mono">{c.phone}</td>
                  <td className="truncate text-ink-muted">{c.email ?? '—'}</td>
                  <td>{c.team ?? '—'}</td>
                  <td>
                    <div className="flex flex-wrap gap-1">
                      {c.tags && c.tags.length > 0 ? (
                        c.tags.map((t) => (
                          <Pill
                            key={t}
                            tone={t === 'VIP' ? 'brand' : 'neutral'}
                          >
                            {t}
                          </Pill>
                        ))
                      ) : (
                        <span className="text-ink-dim">—</span>
                      )}
                    </div>
                  </td>
                  <td className="truncate text-ink-muted">
                    {c.lastCampaign ? (
                      <Badge kind="neutral">{c.lastCampaign}</Badge>
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
