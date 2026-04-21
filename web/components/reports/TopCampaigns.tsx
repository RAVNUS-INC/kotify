import Link from 'next/link';
import type { Route } from 'next';
import type { ReportTopCampaign } from '@/types/report';
import { Card, CardBody, CardHeader, EmptyState } from '@/components/ui';

export type TopCampaignsProps = {
  campaigns: ReadonlyArray<ReportTopCampaign>;
};

export function TopCampaigns({ campaigns }: TopCampaignsProps) {
  return (
    <Card>
      <CardHeader eyebrow="Top 캠페인" title="기간 내 발송량 상위" />
      <CardBody padded={false}>
        {campaigns.length === 0 ? (
          <EmptyState
            icon="zap"
            title="데이터 없음"
            description="기간 내 집계된 캠페인이 없습니다."
            size="sm"
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="k-tbl">
              <thead>
                <tr>
                  <th className="num w-[40px]">#</th>
                  <th>캠페인</th>
                  <th className="num">발송</th>
                  <th className="num">회신률</th>
                </tr>
              </thead>
              <tbody>
                {campaigns.map((c, i) => {
                  const href = `/campaigns/${encodeURIComponent(c.id)}` as Route;
                  return (
                    <tr key={c.id}>
                      <td className="mono text-ink-dim">{i + 1}</td>
                      <td>
                        <Link
                          href={href}
                          className="truncate font-medium text-ink hover:text-brand"
                        >
                          {c.name}
                        </Link>
                      </td>
                      <td className="num">
                        {c.sent.toLocaleString('ko-KR')}
                      </td>
                      <td className="num">{c.replyRate.toFixed(1)}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
