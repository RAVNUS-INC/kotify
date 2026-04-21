import type { TimelineEvent } from '@/types/dashboard';
import { cn } from '@/lib/cn';

export type TimelineRibbonProps = {
  events: ReadonlyArray<TimelineEvent>;
  /** "HH:MM" */
  now: string;
  startHour?: number;
  endHour?: number;
};

function hhmmToMinutes(hhmm: string): number {
  const [h, m] = hhmm.split(':');
  return Number(h ?? 0) * 60 + Number(m ?? 0);
}

const STATE_DOT: Record<TimelineEvent['state'], string> = {
  done: 'bg-gray-9',
  scheduled: 'bg-gray-4 ring-2 ring-gray-2',
  failed: 'bg-danger',
};

export function TimelineRibbon({
  events,
  now,
  startHour = 7,
  endHour = 19,
}: TimelineRibbonProps) {
  const startMin = startHour * 60;
  const endMin = endHour * 60;
  const range = endMin - startMin;
  const nowMin = hhmmToMinutes(now);
  const nowPct = ((nowMin - startMin) / range) * 100;
  const ticks = Array.from({ length: endHour - startHour + 1 }, (_, i) => startHour + i);

  return (
    <div className="rounded-lg border border-line bg-surface p-5">
      <div className="flex items-baseline justify-between">
        <div>
          <div className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-ink-dim">
            Today
          </div>
          <div className="mt-0.5 text-md text-ink-muted">
            {String(startHour).padStart(2, '0')}:00 – {String(endHour).padStart(2, '0')}:00
          </div>
        </div>
        <div className="font-mono text-xs text-ink-muted">
          NOW <span className="font-semibold text-brand">{now}</span>
        </div>
      </div>

      <div className="relative mt-5 h-14">
        <div className="absolute inset-x-0 top-7 h-px bg-gray-3" aria-hidden />

        {ticks.map((hour, i) => {
          const pct = (i / (ticks.length - 1)) * 100;
          return (
            <div
              key={hour}
              className="absolute top-5 -translate-x-1/2"
              style={{ left: `${pct}%` }}
            >
              <div className="mx-auto h-2 w-px bg-gray-4" />
              <div className="mt-1 font-mono text-[10px] text-ink-dim">
                {String(hour).padStart(2, '0')}
              </div>
            </div>
          );
        })}

        {nowPct >= 0 && nowPct <= 100 && (
          <div
            className="absolute top-0 bottom-0 w-px bg-brand"
            style={{ left: `${nowPct}%` }}
            aria-label={`현재 시각 ${now}`}
          >
            <div
              className="absolute top-7 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-brand"
              aria-hidden
            />
          </div>
        )}

        {events.map((e) => {
          const pct = ((hhmmToMinutes(e.time) - startMin) / range) * 100;
          if (pct < 0 || pct > 100) return null;
          return (
            <div
              key={e.id}
              className={cn(
                'absolute top-7 h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full',
                STATE_DOT[e.state],
              )}
              style={{ left: `${pct}%` }}
              title={`${e.time} ${e.label}`}
              aria-label={`${e.time} ${e.label} (${e.state})`}
            />
          );
        })}
      </div>
    </div>
  );
}
