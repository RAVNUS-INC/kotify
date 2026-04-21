import type { ReportDaily } from '@/types/report';
import { AnimatedBars } from '@/components/motion';
import { Card, CardBody, CardHeader } from '@/components/ui';

export type DailyBarsProps = {
  daily: ReportDaily;
};

export function DailyBars({ daily }: DailyBarsProps) {
  const totalSent = daily.sent.reduce((a, b) => a + b, 0);
  const totalReply = daily.reply.reduce((a, b) => a + b, 0);
  const replyRate = totalSent > 0 ? (totalReply / totalSent) * 100 : 0;

  return (
    <Card>
      <CardHeader
        eyebrow="일별 발송"
        title="최근 7일"
        subtitle={`총 ${totalSent.toLocaleString('ko-KR')}건 · 회신 ${replyRate.toFixed(1)}%`}
      />
      <CardBody>
        <AnimatedBars
          data={daily.sent}
          labels={daily.labels}
          height={180}
          staggerStep={40}
          duration={700}
        />

        <div className="mt-4 border-t border-line pt-3">
          <div className="mb-2 font-mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-ink-dim">
            일별 회신
          </div>
          <ul
            role="list"
            aria-label="일별 회신 수"
            className="grid grid-cols-7 gap-1 text-center"
          >
            {daily.labels.map((label, i) => {
              const reply = daily.reply[i] ?? 0;
              return (
                <li
                  key={label}
                  className="flex flex-col items-center gap-0.5"
                >
                  <span className="font-mono text-xs tabular-nums text-ink">
                    {reply}
                  </span>
                  <span className="font-mono text-[10px] text-ink-dim">
                    {label}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      </CardBody>
    </Card>
  );
}
