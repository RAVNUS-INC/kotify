import { redirect } from 'next/navigation';
import { PageHeader } from '@/components/shell';
import {
  ApiKeysList,
  MembersList,
  OrgSettingsForm,
  ProviderSettingsForm,
  SecuritySection,
  SettingsSidebar,
  WebhooksList,
  type SettingsTab,
} from '@/components/settings';
import { Button, Icon } from '@/components/ui';
import {
  fetchApiKeys,
  fetchMembers,
  fetchOrg,
  fetchProviderSettings,
  fetchWebhooks,
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
  const [keys, hooks] = await Promise.all([fetchApiKeys(), fetchWebhooks()]);
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
        <header className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-ink">웹훅</h2>
            <p className="mt-0.5 text-[12.5px] text-ink-muted">
              발송 결과·감사 이벤트를 실시간으로 전달합니다.
            </p>
          </div>
          <Button variant="secondary" size="sm" icon={<Icon name="plus" size={12} />} disabled>
            웹훅 추가
          </Button>
        </header>
        <WebhooksList webhooks={hooks} />
      </section>
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
