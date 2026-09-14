import { redirect } from 'next/navigation';
import { getSession, hasRole } from '@/lib/auth';
import { ForbiddenNotice } from '@/components/error';
import { PageHeader } from '@/components/shell';
import {
  ApiKeysList,
  MembersList,
  OrgSettingsForm,
  ProviderSettingsForm,
  SecuritySection,
  SettingsSidebar,
  SystemUpdatePanel,
  WebhooksList,
  type SettingsTab,
} from '@/components/settings';
import { Button, Icon } from '@/components/ui';
import {
  fetchApiKeys,
  fetchMembers,
  fetchOrg,
  fetchProviderSettings,
  fetchWebhooksWithMeta,
} from '@/lib/settings';

const VALID_TABS: ReadonlyArray<SettingsTab> = [
  'org',
  'messaging',
  'developers',
  'security',
];

type PageProps = {
  params: { tab?: string[] };
};

function resolveTab(segments: string[] | undefined): SettingsTab {
  const first = segments?.[0];
  if (first && (VALID_TABS as ReadonlyArray<string>).includes(first)) {
    return first as SettingsTab;
  }
  return 'org';
}

export default async function SettingsPage({ params }: PageProps) {
  // 백엔드 settings 라우터는 require_role("admin") 전용. 비admin이 링크/URL로
  // 진입하면 하위 fetch 가 403 을 던져 서버 렌더 크래시하므로, 역할을 먼저 확인해
  // 안내 페이지를 렌더한다(백엔드 게이트와 동일 조건 = admin).
  const session = await getSession();
  if (!session || !hasRole(session, 'admin')) {
    return (
      <ForbiddenNotice description="설정은 관리자만 접근할 수 있습니다. 필요하면 관리자에게 권한을 요청하세요." />
    );
  }

  // /settings 로 바로 진입하면 /settings/org로 리다이렉트 — 딥링크 공유에 유리
  if (!params.tab || params.tab.length === 0) {
    redirect('/settings/org');
  }

  // 깊은 경로(/settings/org/extra/here) 방어 — 첫 세그먼트만 유지
  if (params.tab.length > 1) {
    redirect(`/settings/${params.tab[0]}`);
  }

  const tab = resolveTab(params.tab);
  if (tab !== params.tab[0]) {
    // 알 수 없는 탭 — 기본으로
    redirect('/settings/org');
  }

  return (
    <div className="k-page">
      <PageHeader title="설정" sub="조직 · 메시징 · 개발자 · 보안" />

      <div
        className="grid gap-5"
        style={{ gridTemplateColumns: '220px 1fr' }}
      >
        <SettingsSidebar active={tab} />

        <section aria-label={`${tab} 설정`}>
          {tab === 'org' && <OrgTabContent />}
          {tab === 'messaging' && <MessagingTabContent />}
          {tab === 'developers' && <DevelopersTabContent />}
          {tab === 'security' && <SecurityTabContent />}
        </section>
      </div>
    </div>
  );
}

async function OrgTabContent() {
  const org = await fetchOrg();
  return (
    <div className="flex flex-col gap-5">
      <OrgSettingsForm initial={org} />

      <section
        aria-label="멤버"
        className="rounded-lg border border-line bg-surface p-5"
      >
        <header className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-ink">멤버</h2>
            <p className="mt-0.5 text-[12.5px] text-ink-muted">
              역할 변경·초대는 Phase 후속에 연결됩니다.
            </p>
          </div>
          <Button variant="secondary" size="sm" icon={<Icon name="plus" size={12} />} disabled>
            멤버 초대
          </Button>
        </header>
        <MembersListWrapper />
      </section>
    </div>
  );
}

async function MembersListWrapper() {
  const members = await fetchMembers();
  return <MembersList members={members} />;
}

async function MessagingTabContent() {
  const provider = await fetchProviderSettings();
  return <ProviderSettingsForm initial={provider} section="messaging" />;
}

async function DevelopersTabContent() {
  const [keys, hooksResult] = await Promise.all([
    fetchApiKeys(),
    fetchWebhooksWithMeta(),
  ]);
  return (
    <div className="flex flex-col gap-5">
      <section
        aria-label="API 키"
        className="rounded-lg border border-line bg-surface p-5"
      >
        <header className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-ink">API 키</h2>
            <p className="mt-0.5 text-[12.5px] text-ink-muted">
              외부 시스템에서 Kotify를 호출할 때 사용합니다.
            </p>
          </div>
          <Button variant="secondary" size="sm" icon={<Icon name="plus" size={12} />} disabled>
            새 키 발급
          </Button>
        </header>
        <ApiKeysList keys={keys} />
      </section>

      <section
        aria-label="웹훅"
        className="rounded-lg border border-line bg-surface p-5"
      >
        <header className="mb-3">
          <h2 className="text-base font-semibold text-ink">웹훅</h2>
          <p className="mt-0.5 text-[12.5px] text-ink-muted">
            msghub 가 발송 리포트와 고객 회신을 여기로 POST 합니다. 이 URL 을
            msghub 콘솔에 등록하세요.
          </p>
        </header>
        <WebhooksList
          webhooks={hooksResult.webhooks}
          meta={hooksResult.meta}
        />
      </section>

      <SystemUpdatePanel />
    </div>
  );
}

async function SecurityTabContent() {
  const provider = await fetchProviderSettings();
  return (
    <div className="flex flex-col gap-5">
      <ProviderSettingsForm initial={provider} section="security" />
      <SecuritySection />
    </div>
  );
}
