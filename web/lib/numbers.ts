import { apiFetch } from './api';
import type { SenderNumber } from '@/types/number';

export type FetchNumbersParams = {
  status?: string;
};

export async function fetchNumbers(
  params: FetchNumbersParams = {},
): Promise<SenderNumber[]> {
  const qs = new URLSearchParams();
  if (params.status && params.status !== 'all') qs.set('status', params.status);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<SenderNumber[]>(`/numbers${suffix}`);
}
