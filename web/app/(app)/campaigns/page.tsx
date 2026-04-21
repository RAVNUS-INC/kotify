import { PageHeader } from '@/components/shell';
import {
  CampaignsFilters,
  CampaignsTable,
  type CampaignsFilter,
} from '@/components/campaigns';
import { fetchCampaigns } from '@/lib/campaigns';

const VALID_FILTERS: ReadonlyArray<CampaignsFilter> = [
  'all',
  'draft',
  'scheduled',
  'sending',
  'sent',
  'failed',
  'cancelled',
];

function normalizeFilter(raw: string | string[] | undefined): CampaignsFilter {
  if (typeof raw === 'string' && (VALID_FILTERS as ReadonlyArray<string>).includes(raw)) {
    return raw as CampaignsFilter;
  }
  return 'all';
}

type PageProps = {
  searchParams?: {
    status?: string;
    q?: string;
  };
};

export default async function CampaignsPage({ searchParams }: PageProps) {
  const status = normalizeFilter(searchParams?.status);
  const q = searchParams?.q;
  const campaigns = await fetchCampaigns({ status, q });

  return (
    <div className="k-page">
      <PageHeader
        title="발송 이력"
        sub={`${campaigns.length}개 캠페인`}
      />

      <div className="mb-4">
        <CampaignsFilters active={status} q={q} />
      </div>

      <CampaignsTable campaigns={campaigns} />
    </div>
  );
}
