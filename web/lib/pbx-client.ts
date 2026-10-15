/** Client-side PBX 요청 — 팩스 발송·다시 보내기, 연결 테스트. CSRF 토큰은 apiSend 가 붙인다. */
import { apiSend } from './csrf-client';
import type { FaxJob, FaxResolution } from '@/types/pbx';

type Envelope<T> = { data?: T; error?: { code: string; message: string } };

async function readData<T>(res: Response): Promise<T> {
  let body: Envelope<T>;
  try {
    body = (await res.json()) as Envelope<T>;
  } catch {
    throw new Error(`응답을 읽지 못했습니다 (HTTP ${res.status})`);
  }
  if (!res.ok || body.error) {
    throw new Error(body.error?.message ?? `HTTP ${res.status}`);
  }
  if (!body.data) throw new Error('API 응답에 data가 없습니다');
  return body.data;
}

export async function sendFaxClient(input: {
  recipient: string;
  resolution: FaxResolution;
  file: File;
}): Promise<FaxJob> {
  const form = new FormData();
  form.set('recipient', input.recipient);
  form.set('resolution', input.resolution);
  form.set('file', input.file);
  // Content-Type 은 브라우저가 multipart boundary 와 함께 정한다.
  return readData<FaxJob>(await apiSend('/api/fax', { method: 'POST', body: form }));
}

export async function resendFaxClient(id: number): Promise<FaxJob> {
  return readData<FaxJob>(await apiSend(`/api/fax/${id}/resend`, { method: 'POST' }));
}

export async function testPbxConnection(): Promise<{ ok: true; message: string }> {
  return readData<{ ok: true; message: string }>(
    await apiSend('/api/pbx/test', { method: 'POST' }),
  );
}
