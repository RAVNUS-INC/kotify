import { Badge, EmptyState } from '@/components/ui';
import { formatPhone } from '@/lib/phone';
import { fmtKstDateTime, inboxStatusLabel } from '@/lib/pbx-format';
import type { FaxInboxItem } from '@/types/pbx';
import { FaxRefetchButton } from './FaxRefetchButton';

export type FaxInboxTableProps = {
  items: ReadonlyArray<FaxInboxItem>;
  /** 관리자는 PDF 를 못 가져온 건을 다시 가져올 수 있다. */
  canRefetch?: boolean;
};

function sizeLabel(bytes: number | null): string {
  if (!bytes) return '';
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)}MB` : `${Math.max(1, Math.round(bytes / 1024))}KB`;
}

export function FaxInboxTable({ items, canRefetch = false }: FaxInboxTableProps) {
  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-line bg-surface">
        <EmptyState
          icon="inbox"
          title="받은 팩스 없음"
          description="02-3663-9887 로 들어온 팩스가 여기에 보입니다."
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
              <th>받은 시각</th>
              <th>보낸 곳</th>
              <th>상태</th>
              <th>열람</th>
              <th className="text-right">보기</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const status = inboxStatusLabel(item);
              const unread = item.status === 'RECEIVED' && !item.firstViewedAt;
              const number = formatPhone(item.senderNumber) || item.senderNumber || '번호 없음';
              return (
                <tr key={item.id} className={unread ? 'font-medium' : undefined}>
                  <td className="mono">{fmtKstDateTime(item.receivedAt)}</td>
                  <td>
                    {item.senderName ? (
                      <div className="flex flex-col">
                        <span className="truncate text-ink">{item.senderName}</span>
                        <span className="mono text-[12px] text-ink-muted">{number}</span>
                      </div>
                    ) : (
                      <span className="mono text-ink">{number}</span>
                    )}
                  </td>
                  <td>
                    <div className="flex flex-col items-start gap-0.5">
                      <Badge kind={status.kind} dot>
                        {status.label}
                      </Badge>
                      {item.error ? <span className="text-[12px] text-ink-muted">{item.error}</span> : null}
                    </div>
                  </td>
                  <td className="text-[12.5px] text-ink-muted">
                    {unread ? (
                      <Badge kind="brand">새 팩스</Badge>
                    ) : item.firstViewedAt ? (
                      `${fmtKstDateTime(item.firstViewedAt)} · ${item.firstViewedBy ?? '-'}`
                    ) : (
                      '-'
                    )}
                  </td>
                  <td className="text-right">
                    {item.fetchStatus === 'FETCHED' ? (
                      <a
                        href={`/api/fax/inbox/${item.id}/pdf`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm text-ink hover:underline"
                      >
                        PDF 보기 {sizeLabel(item.sizeBytes)}
                      </a>
                    ) : canRefetch && item.fetchStatus === 'FETCH_FAILED' ? (
                      <FaxRefetchButton id={item.id} />
                    ) : (
                      <span className="text-ink-dim">-</span>
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
