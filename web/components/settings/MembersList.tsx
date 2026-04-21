import type { Member } from '@/types/settings';
import { Badge, Button, EmptyState, Icon } from '@/components/ui';
import { cn } from '@/lib/cn';

export type MembersListProps = {
  members: ReadonlyArray<Member>;
};

const ROLE_LABEL: Record<Member['role'], { label: string; kind: 'brand' | 'neutral' }> = {
  owner: { label: 'Owner', kind: 'brand' },
  admin: { label: 'Admin', kind: 'brand' },
  operator: { label: 'Operator', kind: 'neutral' },
  viewer: { label: 'Viewer', kind: 'neutral' },
};

export function MembersList({ members }: MembersListProps) {
  if (members.length === 0) {
    return (
      <EmptyState
        icon="users"
        title="멤버 없음"
        description="초대된 멤버가 없습니다."
        size="sm"
      />
    );
  }

  return (
    <ul role="list" className="flex flex-col divide-y divide-line">
      {members.map((m) => {
        const role = ROLE_LABEL[m.role];
        return (
          <li
            key={m.id}
            className={cn(
              'flex items-center gap-3 py-3',
              !m.active && 'opacity-60',
            )}
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-3 font-mono text-[11px] text-gray-9">
              {m.name.charAt(0)}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-medium text-ink">
                  {m.name}
                </span>
                <Badge kind={role.kind}>{role.label}</Badge>
                {!m.active && <Badge kind="neutral">비활성</Badge>}
              </div>
              <div className="truncate font-mono text-[12.5px] text-ink-dim">
                {m.email}
              </div>
            </div>
            <div className="font-mono text-[11px] text-ink-dim">
              {m.invitedAt}
            </div>
            <Button
              variant="ghost"
              size="sm"
              disabled
              aria-label={`${m.name} 멤버 관리`}
            >
              <Icon name="moreV" size={12} />
            </Button>
          </li>
        );
      })}
    </ul>
  );
}
