import { PageHeader } from '@/components/shell';
import { FaxAutoRefresh, FaxComposer, FaxInboxTable, FaxJobsTable } from '@/components/pbx';
import { LinkSegmented } from '@/components/ui';
import { ADMIN_ROLES, hasAnyRole } from '@/lib/access';
import { getSession } from '@/lib/auth';
import { fetchFaxInbox, fetchFaxJobs } from '@/lib/pbx';
import { hasOpenFax } from '@/lib/pbx-format';

type PageProps = {
  searchParams?: { tab?: string };
};

export default async function FaxPage({ searchParams }: PageProps) {
  const tab = searchParams?.tab === 'inbox' ? 'inbox' : 'all';
  const [session, jobs, inbox] = await Promise.all([
    getSession(),
    tab === 'all' ? fetchFaxJobs({ limit: 50 }) : Promise.resolve(null),
    fetchFaxInbox({ limit: tab === 'inbox' ? 50 : 1 }),
  ]);
  const isAdmin = session ? hasAnyRole(session.roles, ADMIN_ROLES) : false;
  const unread = inbox.meta.unread;

  return (
    <div className="k-page">
      {/* 보낸 팩스 결과 대기 중이거나, 받은 팩스 PDF 를 가져오는 중이면 주기적으로 갱신. */}
      <FaxAutoRefresh
        active={
          jobs ? hasOpenFax(jobs.data) : inbox.data.some((i) => i.fetchStatus === 'PENDING')
        }
      />
      <PageHeader
        title="팩스"
        sub={
          tab === 'inbox'
            ? `02-3663-9887 로 받은 팩스${unread ? ` · 새 팩스 ${unread}건` : ''}`
            : isAdmin
              ? '사내 전화 교환기로 PDF 를 팩스로 보냅니다 · 전체 이력'
              : '사내 전화 교환기로 PDF 를 팩스로 보냅니다'
        }
      />
      <div className="mb-4">
        <LinkSegmented
          aria-label="팩스 구분"
          active={tab}
          basePath="/fax"
          param="tab"
          options={[
            { value: 'all', label: '보낸 팩스' },
            { value: 'inbox', label: '받은 팩스', count: unread || undefined },
          ]}
        />
      </div>
      {tab === 'inbox' ? (
        <FaxInboxTable items={inbox.data} canRefetch={isAdmin} />
      ) : (
        <div className="flex flex-col gap-4">
          <FaxComposer />
          <FaxJobsTable jobs={jobs?.data ?? []} showCreator={isAdmin} />
        </div>
      )}
    </div>
  );
}
