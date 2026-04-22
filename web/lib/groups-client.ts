/**
 * 그룹 mutating 작업 — admin 전용. apiSend 로 CSRF 자동 첨부.
 */

import { apiSend } from './csrf-client';
import type { Group } from '@/types/group';

export type GroupInput = {
  name: string;
  description?: string | null;
};

type Envelope<T> = {
  data?: T;
  error?: { code: string; message: string; fields?: Record<string, string> };
};

async function parse<T>(res: Response): Promise<T> {
  const body = (await res.json()) as Envelope<T>;
  if (!res.ok || body.error) {
    throw new Error(body.error?.message ?? `HTTP ${res.status}`);
  }
  if (body.data === undefined) throw new Error('응답에 data 가 없습니다');
  return body.data;
}

export async function createGroupClient(input: GroupInput): Promise<Group> {
  const res = await apiSend('/api/groups', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  return parse<Group>(res);
}

export async function updateGroupClient(
  id: string,
  patch: Partial<GroupInput>,
): Promise<Group> {
  const res = await apiSend(`/api/groups/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  return parse<Group>(res);
}

export async function deleteGroupClient(id: string): Promise<void> {
  const res = await apiSend(`/api/groups/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
  await parse<{ id: string; deleted: boolean }>(res);
}

export async function addGroupMembersClient(
  id: string,
  contactIds: number[],
): Promise<{ added: number; requested: number }> {
  const res = await apiSend(
    `/api/groups/${encodeURIComponent(id)}/members/add`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contactIds }),
    },
  );
  return parse<{ added: number; requested: number }>(res);
}

export type BulkAddResult = {
  added_existing: number;
  created_new: number;
  skipped_existing_member: number;
  skipped_no_contact: number;
  requested: number;
};

export async function bulkAddGroupMembersClient(
  id: string,
  phones: string[],
  options: { autoCreate?: boolean } = {},
): Promise<BulkAddResult> {
  const res = await apiSend(
    `/api/groups/${encodeURIComponent(id)}/members/bulk-add`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        phones,
        autoCreate: options.autoCreate ?? true,
      }),
    },
  );
  return parse<BulkAddResult>(res);
}

export async function removeGroupMembersClient(
  id: string,
  contactIds: number[],
): Promise<{ removed: number; requested: number }> {
  const res = await apiSend(
    `/api/groups/${encodeURIComponent(id)}/members/remove`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contactIds }),
    },
  );
  return parse<{ removed: number; requested: number }>(res);
}
