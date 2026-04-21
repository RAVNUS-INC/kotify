import { fetchDashboard } from '@/lib/dashboard';
import { PageHeader } from '@/components/shell';
import {
  DashboardActions,
  InboxCard,
  KpiCard,
  RcsDonut,
  TimelineRibbon,
} from '@/components/dash';

export default async function Home() {
  const data = await fetchDashboard();

  return (
    <div className="k-page">
      <PageHeader
        title="오늘의 발송 현황"
        sub={`미답 ${data.inbox.unread}건 · 예약 대기 ${data.kpis.scheduled}건`}
        actions={<DashboardActions />}
      />

      <TimelineRibbon events={data.timeline.events} now={data.timeline.now} />

      <div className="mt-6 grid gap-4 lg:grid-cols-[1.7fr_1fr]">
        <InboxCard threads={data.inbox.threads} unread={data.inbox.unread} />

        <div className="flex flex-col gap-4">
          <div className="rounded-lg border border-gray-10 bg-gray-11 p-5 text-white">
            <div className="flex items-baseline justify-between">
              <div>
                <div className="font-mono text-[10.5px] uppercase tracking-[0.06em] text-gray-5">
                  오늘의 RCS 도달률
                </div>
                <div className="mt-0.5 text-[11.5px] text-gray-6">
                  조직 전체 · 최근 24시간
                </div>
              </div>
            </div>
            <div className="mt-4 flex items-center justify-center text-brand">
              <RcsDonut rate={data.kpis.rcsRate} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <KpiCard
              label="오늘 발송"
              value={data.kpis.todaySent}
              delay={120}
            />
            <KpiCard
              label="예약 대기"
              value={data.kpis.scheduled}
              delay={200}
            />
          </div>

          <KpiCard
            label="오늘 비용"
            value={data.kpis.todayCost}
            format="currency"
            delay={280}
          />
        </div>
      </div>
    </div>
  );
}
