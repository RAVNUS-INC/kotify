import Link from 'next/link';
import type { Route } from 'next';
import type { Campaign } from '@/types/campaign';
import { EmptyState } from '@/components/ui';
import { StatusBadge } from './StatusBadge';

export type CampaignsTableProps = {
  campaigns: ReadonlyArray<Campaign>;
};

function fmtNumber(n: number | null | undefined): string {
  if (n == null) return '—';
  return n.toLocaleString('ko-KR');
}

function fmtCurrency(n: number | null | undefined): string {
  if (n == null || n === 0) return '—';
  return `₩${n.toLocaleString('ko-KR')}`;
}

function fmtRate(reach: number | null | undefined, total: number): string {
  if (reach == null || total === 0) return '—';
  const pct = (reach / total) * 100;
  return `${pct.toFixed(1)}%`;
}

export function CampaignsTable({ campaigns }: CampaignsTableProps) {
  if (campaigns.length === 0) {
    return (
      <div className="rounded-lg border border-line bg-surface">
        <EmptyState
          icon="zap"
          title="캠페인 없음"
          description="검색 조건에 맞는 캠페인이 없습니다."
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
              <th>상태</th>
              <th>캠페인명</th>
              <th className="num">발송</th>
              <th className="num">도달률</th>
              <th className="num">회신</th>
              <th className="num">비용</th>
            </tr>
          </thead>
          <tbody>
            {campaigns.map((c) => {
              const href = `/campaigns/${encodeURIComponent(c.id)}` as Route;
              return (
                <tr key={c.id}>
                  <td className="mono">
                    {c.status === 'scheduled' && c.scheduledAt
                      ? c.scheduledAt
                      : c.createdAt}
                  </td>
                  <td>
                    <StatusBadge status={c.status} />
                  </td>
                  <td>
                    <Link
                      href={href}
                      className="truncate font-medium text-ink hover:text-brand"
                    >
                      {c.name}
                    </Link>
                  </td>
                  <td className="num">{fmtNumber(c.recipients)}</td>
                  <td className="num">
                    {c.status === 'sent' || c.status === 'sending'
                      ? fmtRate(c.reach, c.recipients)
                      : '—'}
                  </td>
                  <td className="num">{fmtNumber(c.replies)}</td>
                  <td className="num">{fmtCurrency(c.cost)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
