import { LinkSegmented, ListSearchInput } from '@/components/ui';
import type { CampaignStatus } from '@/types/campaign';

export type CampaignsFilter = 'all' | CampaignStatus;

const OPTIONS: ReadonlyArray<{ value: CampaignsFilter; label: string }> = [
  { value: 'all', label: '전체' },
  { value: 'sending', label: '진행' },
  { value: 'scheduled', label: '예약' },
  { value: 'failed', label: '실패' },
];

export type CampaignsFiltersProps = {
  active: CampaignsFilter;
  q?: string;
};

export function CampaignsFilters({ active, q }: CampaignsFiltersProps) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="w-full max-w-xs">
        <ListSearchInput placeholder="캠페인명 검색" />
      </div>
      <LinkSegmented
        aria-label="상태 필터"
        active={active}
        options={OPTIONS}
        param="status"
        basePath="/campaigns"
        extraParams={{ q }}
      />
    </div>
  );
}
