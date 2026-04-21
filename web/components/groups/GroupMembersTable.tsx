import Link from 'next/link';
import type { Route } from 'next';
import type { Contact } from '@/types/contact';
import { EmptyState, Pill } from '@/components/ui';

export type GroupMembersTableProps = {
  members: ReadonlyArray<Contact>;
};

export function GroupMembersTable({ members }: GroupMembersTableProps) {
  if (members.length === 0) {
    return (
      <div className="rounded-lg border border-line bg-surface">
        <EmptyState
          icon="users"
          title="멤버 없음"
          description="이 그룹에 속한 연락처가 없습니다."
          size="sm"
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
            </tr>
          </thead>
          <tbody>
            {members.map((m) => {
              const href = `/contacts?selected=${encodeURIComponent(m.id)}` as Route;
              return (
                <tr key={m.id}>
                  <td>
                    <Link
                      href={href}
                      className="flex items-center gap-2 font-medium text-ink hover:text-brand"
                    >
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gray-3 font-mono text-[11px] text-gray-9">
                        {m.name.charAt(0)}
                      </span>
                      <span className="truncate">{m.name}</span>
                    </Link>
                  </td>
                  <td className="mono">{m.phone}</td>
                  <td className="truncate text-ink-muted">{m.email ?? '—'}</td>
                  <td>{m.team ?? '—'}</td>
                  <td>
                    <div className="flex flex-wrap gap-1">
                      {m.tags && m.tags.length > 0 ? (
                        m.tags.map((t) => (
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
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
