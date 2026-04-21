import type { GroupDetail } from '@/types/group';
import { Counter } from '@/components/motion';
import { cn } from '@/lib/cn';

export type GroupKpisProps = {
  group: GroupDetail;
};

export function GroupKpis({ group }: GroupKpisProps) {
  const invalidCount = group.memberCount - group.validCount;

  return (
    <div className="grid grid-cols-4 gap-3">
      <KpiBox label="총 인원">
        <Counter value={group.memberCount} delay={100} duration={800} />
      </KpiBox>
      <KpiBox
        label="유효 번호"
        sub={invalidCount > 0 ? `무효 ${invalidCount}` : '전체 유효'}
      >
        <Counter value={group.validCount} delay={180} duration={800} />
      </KpiBox>
      <KpiBox
        label="최근 도달률"
        sub={
          group.lastCampaignAt
            ? group.lastCampaignAt.split(' ')[0]
            : '발송 이력 없음'
        }
      >
        {group.reachRate != null ? (
          <Counter
            value={group.reachRate}
            format="percent"
            delay={260}
            duration={800}
          />
        ) : (
          <span className="text-ink-dim">—</span>
        )}
      </KpiBox>
      <KpiBox
        label="최근 발송"
        sub={group.lastCampaignAt ? group.lastCampaignAt.split(' ')[1] : undefined}
      >
        <span className="text-[22px] font-mono">
          {group.lastCampaignAt ? group.lastCampaignAt.split(' ')[0] : '—'}
        </span>
      </KpiBox>
    </div>
  );
}

type KpiBoxProps = {
  label: string;
  sub?: string;
  children: React.ReactNode;
};

function KpiBox({ label, sub, children }: KpiBoxProps) {
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
    </div>
  );
}
