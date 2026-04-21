import { PageHeader } from '@/components/shell';
import {
  ChannelBreakdown,
  DailyBars,
  ReportKpiStack,
  TopCampaigns,
} from '@/components/reports';
import { Icon, LinkSegmented } from '@/components/ui';
import { buildReportsCsvHref, fetchReports } from '@/lib/reports';

type PeriodValue = '7d' | '30d' | '90d';

const VALID_PERIODS: ReadonlyArray<PeriodValue> = ['7d', '30d', '90d'];

function normalizePeriod(raw: string | string[] | undefined): PeriodValue {
  if (
    typeof raw === 'string' &&
    (VALID_PERIODS as ReadonlyArray<string>).includes(raw)
  ) {
    return raw as PeriodValue;
  }
  return '7d';
}

const PERIOD_LABEL: Record<PeriodValue, string> = {
  '7d': '최근 7일',
  '30d': '최근 30일',
  '90d': '최근 90일',
};

type PageProps = {
  searchParams?: { period?: string };
};

export default async function ReportsPage({ searchParams }: PageProps) {
  const period = normalizePeriod(searchParams?.period);
  // Phase 9b: 서버는 period 파라미터를 받지만 mock은 고정 데이터 반환.
  // Phase 후속에서 실제 기간 윈도우 집계로 교체.
  const report = await fetchReports();
  const csvHref = buildReportsCsvHref();

  return (
    <div className="k-page">
      <PageHeader
        title="리포트"
        sub={`${PERIOD_LABEL[period]} · ${report.topCampaigns.length}개 캠페인 집계`}
        actions={
          <a
            href={csvHref}
            download
            className="inline-flex h-8 items-center gap-1 rounded border border-gray-4 bg-surface px-2.5 text-sm font-medium text-ink transition-colors duration-fast ease-out hover:bg-gray-1"
          >
            <Icon name="download" size={12} />
            CSV 내보내기
          </a>
        }
      />

      <div className="mb-5 flex items-center gap-3">
        <LinkSegmented
          aria-label="기간"
          active={period}
          basePath="/reports"
          param="period"
          options={[{ value: '7d', label: '7일' }]}
        />
        <span className="font-mono text-[11px] text-ink-dim">
          30일 · 90일은 실제 집계 쿼리 연결 후 제공
        </span>
      </div>

      <ReportKpiStack kpis={report.kpis} />

      <div className="mt-5 grid gap-4 lg:grid-cols-[2fr_1fr]">
        <DailyBars daily={report.daily} />
        <ChannelBreakdown channels={report.channels} />
      </div>

      <div className="mt-5">
        <TopCampaigns campaigns={report.topCampaigns} />
      </div>
    </div>
  );
}
