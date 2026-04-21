import type { Recipient } from '@/types/campaign';
import { EmptyState } from '@/components/ui';
import { RecipientStatusBadge } from './RecipientStatusBadge';

export type RecipientsTableProps = {
  recipients: ReadonlyArray<Recipient>;
};

export function RecipientsTable({ recipients }: RecipientsTableProps) {
  if (recipients.length === 0) {
    return (
      <div className="rounded-lg border border-line bg-surface">
        <EmptyState
          icon="users"
          title="수신자 없음"
          description="아직 발송되지 않았거나 집계 대기 중입니다."
          size="sm"
        />
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface">
      <div className="max-h-[560px] overflow-y-auto">
        <table className="k-tbl">
          <thead className="sticky top-0 z-10 bg-gray-1">
            <tr>
              <th>이름</th>
              <th>번호</th>
              <th>상태</th>
              <th>발송</th>
              <th>읽음</th>
              <th>회신</th>
            </tr>
          </thead>
          <tbody>
            {recipients.map((r) => (
              <tr key={r.id}>
                <td>{r.name}</td>
                <td className="mono">{r.phone}</td>
                <td>
                  <RecipientStatusBadge status={r.status} />
                </td>
                <td className="mono">{r.sentAt ?? '—'}</td>
                <td className="mono">{r.readAt ?? '—'}</td>
                <td className="mono">{r.repliedAt ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
