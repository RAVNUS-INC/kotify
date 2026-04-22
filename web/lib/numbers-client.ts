/**
 * 발신번호 mutating 작업 — admin 전용. 모두 apiSend 로 CSRF 토큰 첨부.
 */

import { apiSend } from './csrf-client';
import type { SenderNumber } from '@/types/number';

type Envelope<T> = {
  data?: T;
  error?: { code: string; message: string; fields?: Record<string, string> };
};

async function readEnvelope<T>(res: Response): Promise<T> {
  const body = (await res.json()) as Envelope<T>;
  if (!res.ok || body.error) {
    throw new Error(body.error?.message ?? `HTTP ${res.status}`);
  }
  if (body.data === undefined) {
    throw new Error('응답에 data 가 없습니다');
  }
  return body.data;
}

export async function createNumberClient(input: {
  number: string;
  label: string;
  rcsEnabled?: boolean;
}): Promise<SenderNumber> {
  const res = await apiSend('/api/numbers', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      number: input.number,
      label: input.label,
      rcsEnabled: input.rcsEnabled ?? false,
    }),
  });
  return readEnvelope<SenderNumber>(res);
}

export async function toggleNumberClient(id: string): Promise<SenderNumber> {
  const res = await apiSend(`/api/numbers/${encodeURIComponent(id)}/toggle`, {
    method: 'POST',
  });
  return readEnvelope<SenderNumber>(res);
}

export async function setDefaultNumberClient(id: string): Promise<SenderNumber> {
  const res = await apiSend(`/api/numbers/${encodeURIComponent(id)}/default`, {
    method: 'POST',
  });
  return readEnvelope<SenderNumber>(res);
}

export async function deleteNumberClient(id: string): Promise<void> {
  const res = await apiSend(`/api/numbers/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
  await readEnvelope<{ id: string; deleted: boolean }>(res);
}
