import { notFound } from 'next/navigation';
import { PageHeader } from '@/components/shell';
import {
  CampaignDetailActions,
  CampaignKpis,
  CampaignMessagePreview,
  FallbackFlow,
  RecipientsTable,
  StatusBadge,
} from '@/components/campaigns';
import { ApiError } from '@/lib/api';
import { getSession, hasRole } from '@/lib/auth';
import { fetchCampaign } from '@/lib/campaigns';

type PageProps = {
  params: { id: string };
};

export default async function CampaignDetail({ params }: PageProps) {
  const id = decodeURIComponent(params.id);

  const session = await getSession();
  // 예약 취소는 sender/admin/owner. viewer/operator 는 버튼 숨김.
  const canCancel = session
    ? hasRole(session, 'sender', 'admin', 'owner')
    : false;

  let campaign;
  try {
    campaign = await fetchCampaign(id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }

  return (
    <div className="k-page">
      <PageHeader
        title={campaign.name}
        sub={
          <span className="flex items-center gap-2">
            <StatusBadge status={campaign.status} />
            <span className="font-mono text-ink-dim">{campaign.createdAt}</span>
            <span className="text-ink-dim">·</span>
            <span>발신 {campaign.sender}</span>
          </span>
        }
        actions={
          <CampaignDetailActions
            campaignId={campaign.id}
            status={campaign.status}
            canCancel={canCancel}
          />
        }
      />

      <CampaignKpis campaign={campaign} />

      <div className="mt-6 grid gap-4 lg:grid-cols-[2fr_1fr]">
        <RecipientsTable recipients={campaign.recipientsSample} />
        <div className="flex flex-col gap-4">
          <CampaignMessagePreview campaign={campaign} />
          <FallbackFlow breakdown={campaign.breakdown} />
        </div>
      </div>

      {campaign.failureReason && (
        <div
          role="alert"
          className="mt-6 rounded-lg border border-danger/30 bg-danger-bg p-4 text-sm text-danger"
        >
          <div className="font-semibold">발송 실패 원인</div>
          <div className="mt-0.5 text-[13px]">{campaign.failureReason}</div>
        </div>
      )}
    </div>
  );
}
