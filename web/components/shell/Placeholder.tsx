import type { ReactNode } from 'react';
import { Icon, type IconName } from '@/components/ui';
import { PageHeader } from './PageHeader';

export type PlaceholderProps = {
  title: string;
  sub?: string;
  phase: string;
  icon?: IconName;
  children?: ReactNode;
};

export function Placeholder({
  title,
  sub,
  phase,
  icon = 'layers',
  children,
}: PlaceholderProps) {
  return (
    <div className="k-page">
      <PageHeader title={title} sub={sub} />
      <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-line bg-surface-subtle py-12 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-surface text-ink-dim">
          <Icon name={icon} size={22} />
        </div>
        <div className="font-mono text-[11px] uppercase tracking-[0.08em] text-brand">
          {phase}
        </div>
        <p className="max-w-[420px] text-sm leading-relaxed text-ink-muted">
          {children ?? '이 화면은 다음 단계에서 구현됩니다.'}
        </p>
      </div>
    </div>
  );
}
