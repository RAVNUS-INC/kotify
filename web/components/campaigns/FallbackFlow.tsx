import type { CampaignBreakdown } from '@/types/campaign';
import { Progress } from '@/components/motion';
import { cn } from '@/lib/cn';

export type FallbackFlowProps = {
  breakdown: CampaignBreakdown;
};

function pct(n: number, total: number): number {
  if (total === 0) return 0;
  return (n / total) * 100;
}

export function FallbackFlow({ breakdown }: FallbackFlowProps) {
  const { total, rcsDelivered, smsFallback, failed } = breakdown;

  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <div className="mb-1 font-mono text-[10.5px] font-medium uppercase tracking-[0.06em] text-ink-dim">
        Fallback 흐름
      </div>
      <div className="mb-3 text-[11px] text-ink-muted">
        RCS 실패 시 SMS로 자동 대체
      </div>

      <div className="flex flex-col gap-2">
        <FlowRow
          label="RCS 도달"
          count={rcsDelivered}
          total={total}
          color="var(--brand)"
          delay={100}
        />
        <FlowRow
          label="SMS 대체"
          count={smsFallback}
          total={total}
          color="var(--warning)"
          delay={220}
        />
        <FlowRow
          label="실패"
          count={failed}
          total={total}
          color="var(--danger)"
          delay={340}
        />
      </div>

      <div className="mt-4 flex items-center justify-between border-t border-line pt-3 font-mono text-[11px]">
        <span className="text-ink-muted">전체 시도</span>
        <span className="font-semibold text-ink tabular-nums">
          {total.toLocaleString('ko-KR')}건
        </span>
      </div>
    </div>
  );
}

type FlowRowProps = {
  label: string;
  count: number;
  total: number;
  color: string;
  delay: number;
};

function FlowRow({ label, count, total, color, delay }: FlowRowProps) {
  const p = pct(count, total);
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between">
        <div className="flex items-center gap-1.5">
          <span
            aria-hidden
            className={cn('inline-block h-1.5 w-1.5 rounded-full')}
            style={{ background: color }}
          />
          <span className="text-[12.5px] text-ink">{label}</span>
        </div>
        <div className="flex items-baseline gap-1.5 font-mono text-[11px]">
          <span className="tabular-nums text-ink">
            {count.toLocaleString('ko-KR')}
          </span>
          <span className="text-ink-dim">({p.toFixed(1)}%)</span>
        </div>
      </div>
      <Progress
        value={p}
        max={100}
        color={color}
        height={3}
        delay={delay}
        duration={700}
        ariaLabel={`${label} ${count}건`}
      />
    </div>
  );
}
