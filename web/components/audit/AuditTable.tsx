import type { AuditEntry } from '@/types/audit';
import { EmptyState } from '@/components/ui';
import { AuditActionBadge } from './AuditActionBadge';

export type AuditTableProps = {
  entries: ReadonlyArray<AuditEntry>;
};

export function AuditTable({ entries }: AuditTableProps) {
  if (entries.length === 0) {
    return (
      <div className="rounded-lg border border-line bg-surface">
        <EmptyState
          icon="fileText"
          title="감사 로그 없음"
          description="검색 조건에 맞는 이벤트가 없습니다."
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
              <th>시간</th>
              <th>주체</th>
              <th>액션</th>
              <th>대상</th>
              <th>IP</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                <td className="mono">{e.time}</td>
                <td>
                  <div className="flex flex-col">
                    <span className="font-medium text-ink">{e.actor}</span>
                    <span className="font-mono text-[11px] text-ink-dim">
                      {e.actorEmail}
                    </span>
                  </div>
                </td>
                <td>
                  <AuditActionBadge action={e.action} />
                </td>
                <td className="truncate text-ink-muted">{e.target}</td>
                <td className="mono text-ink-dim">{e.ip}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
