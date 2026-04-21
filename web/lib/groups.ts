import { apiFetch } from './api';
import type { Group, GroupDetail } from '@/types/group';

export type FetchGroupsParams = {
  q?: string;
};

export async function fetchGroups(
  params: FetchGroupsParams = {},
): Promise<Group[]> {
  const qs = new URLSearchParams();
  if (params.q) qs.set('q', params.q);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<Group[]>(`/groups${suffix}`);
}

export async function fetchGroup(id: string): Promise<GroupDetail> {
  return apiFetch<GroupDetail>(`/groups/${encodeURIComponent(id)}`);
}
