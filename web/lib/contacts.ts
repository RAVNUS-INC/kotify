import { apiFetch } from './api';
import type { Contact, ContactDetail } from '@/types/contact';

export type FetchContactsParams = {
  q?: string;
  groupId?: string;
  tag?: string;
};

export async function fetchContacts(
  params: FetchContactsParams = {},
): Promise<Contact[]> {
  const qs = new URLSearchParams();
  if (params.q) qs.set('q', params.q);
  if (params.groupId) qs.set('groupId', params.groupId);
  if (params.tag) qs.set('tag', params.tag);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<Contact[]>(`/contacts${suffix}`);
}

export async function fetchContact(id: string): Promise<ContactDetail> {
  return apiFetch<ContactDetail>(`/contacts/${encodeURIComponent(id)}`);
}
