import { PageHeader } from '@/components/shell';
import { GroupCard, GroupsAdminShell } from '@/components/groups';
import { EmptyState, ListSearchInput } from '@/components/ui';
import { getSession, hasRole } from '@/lib/auth';
import { fetchGroups } from '@/lib/groups';

type PageProps = {
  searchParams?: { q?: string };
};

export default async function GroupsPage({ searchParams }: PageProps) {
  const q = searchParams?.q;
  const [session, groups] = await Promise.all([
    getSession(),
    fetchGroups({ q }),
  ]);
  const canManage = session ? hasRole(session, 'admin', 'owner', 'sender') : false;

  return (
    <div className="k-page">
      <PageHeader
        title="그룹"
        sub={`${groups.length}개 그룹`}
        actions={<GroupsAdminShell canManage={canManage} />}
      />

      <div className="mb-4">
        <div className="w-full max-w-xs">
          <ListSearchInput placeholder="그룹명·설명 검색" />
        </div>
      </div>

      {groups.length === 0 ? (
        <div className="rounded-lg border border-line bg-surface">
          <EmptyState
            icon="user2"
            title="그룹 없음"
            description="검색 조건에 맞는 그룹이 없습니다."
            size="md"
          />
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {groups.map((g) => (
            <GroupCard key={g.id} group={g} />
          ))}
        </div>
      )}
    </div>
  );
}
