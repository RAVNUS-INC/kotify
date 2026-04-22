import Link from 'next/link';
import { notFound } from 'next/navigation';
import { PageHeader } from '@/components/shell';
import {
  GroupDetailAdminShell,
  GroupKpis,
  GroupMembersTable,
} from '@/components/groups';
import { Badge, Button, Icon } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { getSession, hasRole } from '@/lib/auth';
import { fetchGroup } from '@/lib/groups';

type PageProps = {
  params: { id: string };
};

const SOURCE_LABEL: Record<string, string> = {
  ad: 'AD 동기화',
  csv: 'CSV 업로드',
  api: 'API 연동',
  manual: '수동 관리',
};

export default async function GroupDetailPage({ params }: PageProps) {
  const id = decodeURIComponent(params.id);

  const session = await getSession();
  const canManage = session ? hasRole(session, 'admin', 'owner', 'sender') : false;

  let group;
  try {
    group = await fetchGroup(id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }

  return (
    <div className="k-page">
      <PageHeader
        title={group.name}
        sub={
          <span className="flex items-center gap-2">
            <Badge kind={group.source === 'ad' ? 'brand' : 'neutral'}>
              {SOURCE_LABEL[group.source] ?? group.source}
            </Badge>
            {group.description && (
              <span className="text-ink-muted">· {group.description}</span>
            )}
          </span>
        }
        actions={
          <div className="flex items-center gap-2">
            <Link
              href="/groups"
              className="inline-flex h-8 items-center gap-1 rounded border border-gray-4 bg-surface px-2.5 text-sm text-ink-muted transition-colors duration-fast ease-out hover:bg-gray-1"
            >
              <Icon name="arrowLeft" size={12} />
              그룹 목록
            </Link>
            <GroupDetailAdminShell group={group} canManage={canManage} />
          </div>
        }
      />

      <GroupKpis group={group} />

      <div className="mt-6">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="font-mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-ink-dim">
            멤버 ({group.members.length}명)
          </h2>
          {group.lastSyncAt && (
            <div className="font-mono text-[11px] text-ink-dim">
              마지막 동기화 · {group.lastSyncAt}
            </div>
          )}
        </div>
        <GroupMembersTable members={group.members} />
      </div>
    </div>
  );
}
