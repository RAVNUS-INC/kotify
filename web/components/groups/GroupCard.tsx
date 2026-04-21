import Link from 'next/link';
import type { Route } from 'next';
import type { Group, GroupSource } from '@/types/group';
import { Icon, type IconName } from '@/components/ui';
import { cn } from '@/lib/cn';

export type GroupCardProps = {
  group: Group;
};

const SOURCE_MAP: Record<
  GroupSource,
  { label: string; icon: IconName; tone: 'brand' | 'neutral' }
> = {
  ad: { label: 'AD', icon: 'building', tone: 'brand' },
  csv: { label: 'CSV', icon: 'fileText', tone: 'neutral' },
  api: { label: 'API', icon: 'database', tone: 'neutral' },
  manual: { label: '수동', icon: 'user', tone: 'neutral' },
};

export function GroupCard({ group }: GroupCardProps) {
  const src = SOURCE_MAP[group.source];
  const href = `/groups/${encodeURIComponent(group.id)}` as Route;

  return (
    <Link
      href={href}
      className={cn(
        'group flex flex-col gap-3 rounded-lg border border-line bg-surface p-4',
        'transition-all duration-fast ease-out hover:border-brand/40 hover:shadow-sm',
        'focus-visible:outline-none focus-visible:shadow-[0_0_0_3px_rgba(59,0,139,0.12)]',
      )}
      aria-label={`${group.name} 그룹 (${group.memberCount}명)`}
    >
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-base font-semibold text-ink group-hover:text-brand">
            {group.name}
          </h3>
          {group.description && (
            <p className="mt-0.5 truncate text-[12.5px] text-ink-muted">
              {group.description}
            </p>
          )}
        </div>
        <span
          className={cn(
            'inline-flex shrink-0 items-center gap-1 rounded-full border px-1.5 py-0.5 font-mono text-[10.5px] font-medium',
            src.tone === 'brand'
              ? 'border-brand-border bg-brand-soft text-brand'
              : 'border-line bg-gray-1 text-gray-8',
          )}
        >
          <Icon name={src.icon} size={10} />
          {src.label}
        </span>
      </header>

      <div className="flex items-baseline justify-between gap-2">
        <div>
          <div className="font-mono text-[10.5px] uppercase tracking-[0.06em] text-ink-dim">
            인원
          </div>
          <div className="mt-0.5 text-[22px] font-semibold leading-none tracking-[-0.02em] tabular-nums text-ink">
            {group.memberCount.toLocaleString('ko-KR')}
            <span className="ml-0.5 text-sm font-normal text-ink-muted">명</span>
          </div>
        </div>
        {group.reachRate != null && (
          <div className="text-right">
            <div className="font-mono text-[10.5px] uppercase tracking-[0.06em] text-ink-dim">
              최근 도달률
            </div>
            <div className="mt-0.5 font-mono text-sm tabular-nums text-ink">
              {group.reachRate.toFixed(1)}%
            </div>
          </div>
        )}
      </div>

      <footer className="flex items-center justify-between border-t border-line pt-2 font-mono text-[11px] text-ink-dim">
        <span>
          동기화 {group.lastSyncAt ? group.lastSyncAt.split(' ')[0] : '—'}
        </span>
        <span className="flex items-center gap-1">
          <Icon name="arrowRight" size={11} />
        </span>
      </footer>
    </Link>
  );
}
