import type { CampaignDetail } from '@/types/campaign';
import { Counter, Progress } from '@/components/motion';
import { cn } from '@/lib/cn';

export type CampaignKpisProps = {
  campaign: CampaignDetail;
};

export function CampaignKpis({ campaign }: CampaignKpisProps) {
  const total = campaign.recipients;
  const reach = campaign.reach ?? 0;
  const replies = campaign.replies ?? 0;
  const cost = campaign.cost;
  const reachRate = total > 0 ? (reach / total) * 100 : 0;
  const replyRate = total > 0 ? (replies / total) * 100 : 0;

  return (
    <div className="grid grid-cols-4 gap-3">
      <KpiBox label="총 발송" delay={100}>
        <Counter value={total} delay={100} />
      </KpiBox>
      <KpiBox
        label="도달"
        delay={180}
        sub={`${reachRate.toFixed(1)}%`}
        progress={reachRate}
      >
        <Counter value={reach} delay={180} />
      </KpiBox>
      <KpiBox
        label="회신"
        delay={260}
        sub={`${replyRate.toFixed(1)}%`}
        progress={replyRate}
        progressColor="var(--success)"
      >
        <Counter value={replies} delay={260} />
      </KpiBox>
      <KpiBox label="비용" delay={340}>
        <Counter value={cost} format="currency" delay={340} />
      </KpiBox>
    </div>
  );
}

type KpiBoxProps = {
  label: string;
  delay: number;
  sub?: string;
  progress?: number;
  progressColor?: string;
  children: React.ReactNode;
};

function KpiBox({
  label,
  sub,
  progress,
  progressColor = 'var(--brand)',
  delay,
  children,
}: KpiBoxProps) {
  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <div className="font-mono text-[10.5px] font-medium uppercase tracking-[0.06em] text-ink-dim">
        {label}
      </div>
      <div
        className={cn(
          'mt-1.5 text-[28px] font-semibold leading-none tracking-[-0.03em] text-ink',
        )}
      >
        {children}
      </div>
      {sub && (
        <div className="mt-1 font-mono text-[11px] text-ink-muted">{sub}</div>
      )}
      {progress !== undefined && (
        <div className="mt-3">
          <Progress
            value={progress}
            max={100}
            color={progressColor}
            duration={1000}
            delay={delay + 200}
            ariaLabel={label}
          />
        </div>
      )}
    </div>
  );
}
