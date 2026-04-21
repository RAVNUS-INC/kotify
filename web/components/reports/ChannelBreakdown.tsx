import type { ReportChannels } from '@/types/report';
import { Progress } from '@/components/motion';
import { Card, CardBody, CardHeader } from '@/components/ui';

export type ChannelBreakdownProps = {
  channels: ReportChannels;
};

const CHANNEL_LABEL = {
  rcs: 'RCS',
  sms: 'SMS',
  lms: 'LMS',
  kakao: '카카오',
} as const;

const CHANNEL_COLOR = {
  rcs: 'var(--brand)',
  sms: 'var(--gray-9)',
  lms: 'var(--gray-7)',
  kakao: '#fee500',
} as const;

export function ChannelBreakdown({ channels }: ChannelBreakdownProps) {
  const entries = (
    ['rcs', 'sms', 'lms', 'kakao'] as const
  ).map((k, i) => ({
    key: k,
    label: CHANNEL_LABEL[k],
    color: CHANNEL_COLOR[k],
    count: channels[k].count,
    rate: channels[k].rate,
    delay: 200 + i * 120,
  }));

  return (
    <Card className="h-full">
      <CardHeader eyebrow="채널 구성" title="채널별 비중" />
      <CardBody>
        <div className="flex flex-col gap-3">
          {entries.map((e) => (
            <div key={e.key} className="flex flex-col gap-1">
              <div className="flex items-baseline justify-between gap-2">
                <div className="flex items-center gap-1.5">
                  <span
                    aria-hidden
                    className="inline-block h-1.5 w-1.5 rounded-full"
                    style={{ background: e.color }}
                  />
                  <span className="text-[12.5px] font-medium text-ink">
                    {e.label}
                  </span>
                </div>
                <div className="flex items-baseline gap-1.5 font-mono text-[11px]">
                  <span className="tabular-nums text-ink">
                    {e.count.toLocaleString('ko-KR')}
                  </span>
                  <span className="text-ink-dim">({e.rate.toFixed(1)}%)</span>
                </div>
              </div>
              <Progress
                value={e.rate}
                max={100}
                color={e.color}
                height={4}
                delay={e.delay}
                duration={900}
                ariaLabel={`${e.label} ${e.rate}%`}
              />
            </div>
          ))}
        </div>
      </CardBody>
    </Card>
  );
}
