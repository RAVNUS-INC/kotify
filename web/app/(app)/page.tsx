import Link from 'next/link';
import { fetchDashboard } from '@/lib/dashboard';
import { fetchCampaigns } from '@/lib/campaigns';
import { PageHeader } from '@/components/shell';
import { CampaignsTable } from '@/components/campaigns';
import { DashboardActions, InboxCard, KpiCard, TodaySchedule } from '@/components/dash';

// 홈에 보여줄 최근 캠페인 수 — 나머지는 발송 이력에서 본다.
const RECENT_CAMPAIGNS = 5;

export default async function Home() {
  const [data, campaigns] = await Promise.all([fetchDashboard(), fetchCampaigns()]);
  const recent = campaigns.slice(0, RECENT_CAMPAIGNS);

  return (
    <div className="k-page flex flex-col gap-6">
      <PageHeader
        className="!mb-0"
        title="오늘의 발송 현황"
        sub={`답장 대기 ${data.inbox.unread}건 · 예약 대기 ${data.kpis.scheduled}건`}
        actions={<DashboardActions />}
      />

      <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-4">
        <KpiCard label="오늘 발송" value={data.kpis.todaySent} delay={80} />
        <KpiCard
          label="RCS 도달률"
          value={data.kpis.rcsRate}
          format="percent"
          fractionDigits={1}
          meter={data.kpis.rcsRate}
          delay={140}
        />
        <KpiCard label="답장 대기" value={data.inbox.unread} delay={200} />
        <KpiCard
          label="오늘 비용"
          value={data.kpis.todayCost}
          format="currency"
          delta={
            data.kpis.monthCost != null
              ? { text: `이번 달 ₩${data.kpis.monthCost.toLocaleString('ko-KR')}` }
              : undefined
          }
          delay={260}
        />
      </div>

      <div className="grid items-stretch gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <InboxCard
          threads={data.inbox.threads}
          unread={data.inbox.unread}
          today={data.inbox.today}
        />
        <TodaySchedule events={data.timeline.events} now={data.timeline.now} />
      </div>

      <section aria-labelledby="recent-campaigns" className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 id="recent-campaigns" className="m-0 text-[15px] font-semibold leading-[22px] text-ink">
            최근 발송
          </h2>
          <Link href="/campaigns" className="k-link text-md">
            발송 이력 전체
          </Link>
        </div>
        <CampaignsTable
          campaigns={recent}
          emptyDescription="아직 보낸 캠페인이 없습니다. 새 발송으로 첫 캠페인을 만들어 보세요."
        />
      </section>
    </div>
  );
}
