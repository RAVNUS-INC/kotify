import { PageHeader } from '@/components/shell';
import { FaxAutoRefresh, FaxComposer, FaxJobsTable } from '@/components/pbx';
import { ADMIN_ROLES, hasAnyRole } from '@/lib/access';
import { getSession } from '@/lib/auth';
import { fetchFaxJobs } from '@/lib/pbx';
import { hasOpenFax } from '@/lib/pbx-format';

export default async function FaxPage() {
  const [session, jobs] = await Promise.all([getSession(), fetchFaxJobs({ limit: 50 })]);
  const isAdmin = session ? hasAnyRole(session.roles, ADMIN_ROLES) : false;

  return (
    <div className="k-page">
      <FaxAutoRefresh active={hasOpenFax(jobs.data)} />
      <PageHeader
        title="팩스"
        sub={isAdmin ? '사내 전화 교환기로 PDF 를 팩스로 보냅니다 · 전체 이력' : '사내 전화 교환기로 PDF 를 팩스로 보냅니다'}
      />
      <div className="flex flex-col gap-4">
        <FaxComposer />
        <FaxJobsTable jobs={jobs.data} showCreator={isAdmin} />
      </div>
    </div>
  );
}
