import { apiFetch } from './api';
import type { Campaign, CampaignDetail } from '@/types/campaign';

export type FetchCampaignsParams = {
  q?: string;
  status?: string;
};

export async function fetchCampaigns(
  params: FetchCampaignsParams = {},
): Promise<Campaign[]> {
  const qs = new URLSearchParams();
  if (params.q) qs.set('q', params.q);
  if (params.status && params.status !== 'all') qs.set('status', params.status);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<Campaign[]>(`/campaigns${suffix}`);
}

export async function fetchCampaign(id: string): Promise<CampaignDetail> {
  return apiFetch<CampaignDetail>(`/campaigns/${encodeURIComponent(id)}`);
}
