import type { ReportKpi, ReportKpis } from '@/types/report';
import { Counter, Sparkline } from '@/components/motion';
import type { CounterFormat } from '@/components/motion';
import { cn } from '@/lib/cn';

export type ReportKpiStackProps = {
  kpis: ReportKpis;
};

export function ReportKpiStack({ kpis }: ReportKpiStackProps) {
  return (
    <div className="grid grid-cols-4 gap-3">
      <KpiCell
        label="총 발송"
        kpi={kpis.totalSent}
        format="number"
        delay={100}
      />
      <KpiCell
        label="평균 도달률"
        kpi={kpis.avgDeliveryRate}
        format="percent"
        delay={180}
      />
      <KpiCell
        label="총 회신"
        kpi={kpis.replies}
        format="number"
        delay={260}
      />
      <KpiCell
        label="총 비용"
        kpi={kpis.cost}
        format="currency"
        delay={340}
      />
    </div>
  );
}

type KpiCellProps = {
  label: string;
  kpi: ReportKpi;
  format: CounterFormat;
  delay: number;
};

function KpiCell({ label, kpi, format, delay }: KpiCellProps) {
  const deltaColor =
    kpi.deltaDir === 'up'
      ? 'text-success'
      : kpi.deltaDir === 'down'
        ? 'text-danger'
        : 'text-ink-muted';

  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <div className="font-mono text-[10.5px] font-medium uppercase tracking-[0.06em] text-ink-dim">
        {label}
      </div>
      <div className="mt-1.5 text-[28px] font-semibold leading-none tracking-[-0.03em] text-ink">
        <Counter value={kpi.value} format={format} delay={delay} duration={800} />
      </div>
      <div className="mt-1 flex items-center gap-1.5">
        <span className={cn('font-mono text-[11px] font-medium', deltaColor)}>
          {kpi.delta}
        </span>
        <span className="font-mono text-[10.5px] text-ink-dim">vs 지난 주</span>
      </div>
      <div className="mt-3">
        <Sparkline
          data={kpi.spark}
          width={160}
          height={32}
          delay={delay + 200}
          duration={800}
          color="var(--brand)"
        />
      </div>
    </div>
  );
}
