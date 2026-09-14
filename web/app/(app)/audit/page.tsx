import { getSession, hasRole } from '@/lib/auth';
import { ForbiddenNotice } from '@/components/error';
import { PageHeader } from '@/components/shell';
import { AuditTable } from '@/components/audit';
import { Icon, LinkSegmented, ListSearchInput } from '@/components/ui';
import { buildAuditCsvHref, fetchAudit } from '@/lib/audit';

const ACTION_OPTIONS = [
  { value: 'all', label: '전체' },
  { value: 'LOGIN', label: 'LOGIN' },
  { value: 'CREATE_CAMPAIGN', label: 'CREATE_CAMPAIGN' },
  { value: 'CAMPAIGN_FAILED', label: 'CAMPAIGN_FAILED' },
  { value: 'PATCH_ORG', label: 'PATCH_ORG' },
] as const;

type PageProps = {
  searchParams?: {
    q?: string;
    action?: string;
  };
};

export default async function AuditPage({ searchParams }: PageProps) {
  // 감사 로그 백엔드는 require_role("admin") 전용. 비admin 진입 시 fetchAudit 가
  // 403 → 서버 렌더 크래시하므로 역할을 먼저 확인해 안내 페이지를 렌더한다.
  const session = await getSession();
  if (!session || !hasRole(session, 'admin')) {
    return (
      <ForbiddenNotice description="감사 로그는 관리자만 열람할 수 있습니다. 필요하면 관리자에게 권한을 요청하세요." />
    );
  }

  const q = searchParams?.q;
  const action = searchParams?.action ?? 'all';
  const entries = await fetchAudit({ q, action });
  const csvHref = buildAuditCsvHref({ q, action });

  return (
    <div className="k-page">
      <PageHeader
        title="감사 로그"
        sub={`${entries.length}건`}
        actions={
          <a
            href={csvHref}
            download
            className="inline-flex h-8 items-center gap-1 rounded border border-gray-4 bg-surface px-2.5 text-sm font-medium text-ink transition-colors duration-fast ease-out hover:bg-gray-1"
          >
            <Icon name="download" size={12} />
            CSV 내보내기
          </a>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="w-full max-w-xs">
          <ListSearchInput placeholder="주체·이메일·대상 검색" />
        </div>
        <LinkSegmented
          aria-label="액션 필터"
          active={action}
          basePath="/audit"
          param="action"
          options={[...ACTION_OPTIONS]}
          extraParams={{ q }}
        />
      </div>

      <AuditTable entries={entries} />
    </div>
  );
}
