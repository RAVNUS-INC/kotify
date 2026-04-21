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
  dark?: boolean;
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
  dark = false,
  fractionDigits,
  className,
}: KpiCardProps) {
  return (
    <div
      className={cn(
        'rounded-lg border p-4',
        dark
          ? 'border-gray-10 bg-gray-11 text-white'
          : 'border-line bg-surface text-ink',
        className,
      )}
    >
      <div
        className={cn(
          'font-mono text-[10.5px] font-medium uppercase tracking-[0.06em]',
          dark ? 'text-gray-5' : 'text-ink-dim',
        )}
      >
        {label}
      </div>
      <div
        className={cn(
          'mt-1.5 text-[28px] font-semibold leading-none tracking-[-0.03em]',
          dark ? 'text-white' : 'text-ink',
        )}
      >
        <Counter
          value={value}
          format={format}
          delay={delay}
          fractionDigits={fractionDigits}
        />
      </div>
      {delta && (
        <div
          className={cn(
            'mt-1 inline-flex items-center gap-1 font-mono text-[11px]',
            delta.direction === 'down' && 'text-danger',
            delta.direction === 'up' && 'text-success',
            (!delta.direction || delta.direction === 'flat') &&
              (dark ? 'text-gray-5' : 'text-ink-muted'),
          )}
        >
          {delta.text}
        </div>
      )}
      {spark && (
        <div className="mt-3">
          <Sparkline
            data={spark}
            width={140}
            height={28}
            delay={delay + 200}
            color={dark ? '#ffffff' : 'var(--brand)'}
          />
        </div>
      )}
    </div>
  );
}
