import Link from 'next/link';
import { notFound } from 'next/navigation';
import { PageHeader } from '@/components/shell';
import {
  CampaignKpis,
  CampaignMessagePreview,
  FallbackFlow,
  RecipientsTable,
  StatusBadge,
} from '@/components/campaigns';
import { Button, Icon } from '@/components/ui';
import { fetchCampaign } from '@/lib/campaigns';
import { ApiError } from '@/lib/api';

type PageProps = {
  params: { id: string };
};

export default async function CampaignDetail({ params }: PageProps) {
  const id = decodeURIComponent(params.id);

  let campaign;
  try {
    campaign = await fetchCampaign(id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }

  const isCancellable = campaign.status === 'scheduled' || campaign.status === 'sending';
  const isRetryable = campaign.status === 'failed';

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
          <>
            <Link
              href="/campaigns"
              className="inline-flex h-8 items-center gap-1 rounded border border-gray-4 bg-surface px-2.5 text-sm text-ink-muted transition-colors duration-fast ease-out hover:bg-gray-1"
            >
              <Icon name="arrowLeft" size={12} />
              목록
            </Link>
            {isRetryable && (
              <Button variant="primary" size="sm" icon={<Icon name="refresh" size={12} />}>
                재발송
              </Button>
            )}
            {isCancellable && (
              <Button variant="danger" size="sm" icon={<Icon name="x" size={12} />}>
                취소
              </Button>
            )}
          </>
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
