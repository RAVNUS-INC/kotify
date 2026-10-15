import type { TimelineEvent, TimelineEventState } from '@/types/dashboard';
import { Card, CardHeader, EmptyState, Pill, type PillTone } from '@/components/ui';

export type TodayScheduleProps = {
  events: ReadonlyArray<TimelineEvent>;
  /** "HH:MM" (KST) — 대시보드 응답 시각 */
  now: string;
};

const STATE: Record<TimelineEventState, { label: string; tone: PillTone }> = {
  done: { label: '완료', tone: 'success' },
  scheduled: { label: '예약', tone: 'brand' },
  failed: { label: '실패', tone: 'danger' },
};

/**
 * 오늘 만든 캠페인을 시각 순으로 보여준다. 예전 07–19시 눈금(TimelineRibbon)은 점만 찍혀
 * 무엇이 언제 나갔는지 읽을 수 없었다 → 시각·이름·상태를 한 줄씩 적는다.
 * 상태는 색만이 아니라 글자로도 보인다.
 */
export function TodaySchedule({ events, now }: TodayScheduleProps) {
  const sorted = [...events].sort((a, b) => a.time.localeCompare(b.time));
  return (
    <Card className="flex h-full flex-col">
      <CardHeader
        title="오늘 일정"
        actions={<span className="text-xs tabular-nums text-ink-dim">{now} 기준</span>}
      />
      {sorted.length === 0 ? (
        <EmptyState
          icon="clock"
          title="오늘 발송한 캠페인이 없습니다"
          description="새 발송이나 예약을 만들면 여기에 시각 순으로 표시됩니다."
          size="sm"
        />
      ) : (
        <ol className="m-0 flex list-none flex-col p-0">
          {sorted.map((e) => {
            const s = STATE[e.state];
            return (
              <li
                key={e.id}
                className="grid grid-cols-[48px_minmax(0,1fr)_auto] items-center gap-3 border-b border-line px-5 py-3 last:border-b-0"
              >
                <span className="tabular-nums text-md text-ink-muted">{e.time}</span>
                <span className="truncate text-md font-semibold text-ink">{e.label}</span>
                <Pill tone={s.tone}>{s.label}</Pill>
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}
