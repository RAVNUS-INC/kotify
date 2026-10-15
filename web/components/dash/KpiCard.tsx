import { Counter, Sparkline } from '@/components/motion';
import type { CounterFormat } from '@/components/motion';
import { cn } from '@/lib/cn';

export type KpiDelta = {
  text: string;
  direction?: 'up' | 'down' | 'flat';
};

export type KpiCardProps = {
  label: string;
  value: number;
  format?: CounterFormat;
  delta?: KpiDelta;
  spark?: ReadonlyArray<number>;
  delay?: number;
  /** 0-100. 주면 숫자 아래에 막대(도달률 등)를 그린다 */
  meter?: number;
  fractionDigits?: number;
  className?: string;
};

export function KpiCard({
  label,
  value,
  format,
  delta,
  spark,
  delay = 100,
  meter,
  fractionDigits,
  className,
}: KpiCardProps) {
  return (
    <div
      className={cn(
        'flex flex-col gap-2 rounded-lg border border-line bg-surface p-5 text-ink shadow-sm',
        className,
      )}
    >
      <div className="text-xs font-semibold text-ink-muted">{label}</div>
      <div className="text-[30px] font-bold leading-[38px] tracking-[-0.02em] tabular-nums text-ink">
        <Counter
          value={value}
          format={format}
          delay={delay}
          fractionDigits={fractionDigits}
        />
      </div>
      {meter != null && (
        <div
          className="h-1.5 overflow-hidden rounded-full bg-surface-hover"
          role="img"
          aria-label={`${label} ${meter.toFixed(1)}%`}
        >
          <div
            className="h-full rounded-full bg-brand"
            style={{ width: `${Math.min(Math.max(meter, 0), 100)}%` }}
          />
        </div>
      )}
      {delta && (
        <div
          className={cn(
            'inline-flex items-center gap-1 tabular-nums text-xs',
            delta.direction === 'down' && 'text-danger',
            delta.direction === 'up' && 'text-success',
            (!delta.direction || delta.direction === 'flat') && 'text-ink-dim',
          )}
        >
          {delta.text}
        </div>
      )}
      {spark && (
        <div>
          <Sparkline
            data={spark}
            width={140}
            height={28}
            delay={delay + 200}
            color="var(--brand)"
          />
        </div>
      )}
    </div>
  );
}
