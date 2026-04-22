/**
 * 연락처 mutating 작업 client-side. apiSend 로 CSRF 자동 첨부.
 */

import { apiSend } from './csrf-client';
import type { Contact } from '@/types/contact';

export type ContactInput = {
  name: string;
  phone?: string | null;
  email?: string | null;
  team?: string | null;
  notes?: string | null;
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

export async function createContactClient(input: ContactInput): Promise<Contact> {
  const res = await apiSend('/api/contacts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  return parse<Contact>(res);
}

export async function updateContactClient(
  id: string,
  patch: Partial<ContactInput>,
): Promise<Contact> {
  const res = await apiSend(`/api/contacts/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  return parse<Contact>(res);
}

export async function deleteContactClient(id: string): Promise<void> {
  const res = await apiSend(`/api/contacts/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
  await parse<{ id: string; deleted: boolean }>(res);
}

export type ImportMode = 'skip' | 'update' | 'create';

export type ImportResult = {
  created: number;
  updated: number;
  skipped: number;
  invalid: number;
  errors: string[];
  invalidPreview: Array<{ row: number; error?: string; [k: string]: unknown }>;
};

export async function importContactsClient(
  file: File,
  mode: ImportMode = 'skip',
): Promise<ImportResult> {
  const form = new FormData();
  form.append('file', file);
  form.append('mode', mode);
  // FormData 는 Content-Type 을 자동으로 multipart/form-data; boundary=... 로
  // 설정해주므로 여기서 명시 헤더 주면 안 됨.
  const res = await apiSend('/api/contacts/import', {
    method: 'POST',
    body: form,
  });
  return parse<ImportResult>(res);
}

/**
 * CSV 내보내기 — 브라우저가 직접 다운로드 받도록 a[href] 로 유도한다.
 * (이 함수는 URL 만 반환 — 컴포넌트에서 <a href> 로 사용.)
 */
export function buildContactsExportHref(): string {
  return '/api/contacts/export.csv';
}
