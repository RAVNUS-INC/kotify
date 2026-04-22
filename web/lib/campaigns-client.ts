/**
 * 캠페인 mutating 작업. apiSend 로 CSRF 자동 첨부.
 */

import { apiSend } from './csrf-client';

type Envelope<T> = {
  data?: T;
  error?: { code: string; message: string };
};

async function parse<T>(res: Response): Promise<T> {
  const body = (await res.json()) as Envelope<T>;
  if (!res.ok || body.error) {
    throw new Error(body.error?.message ?? `HTTP ${res.status}`);
  }
  if (body.data === undefined) throw new Error('응답에 data 가 없습니다');
  return body.data;
}

export type CancelResult = {
  id: string;
  status: string;
  message: string;
};

/**
 * 예약 캠페인 취소. 상태가 RESERVED 가 아니면 400, 권한 없으면 403,
 * msghub 설정 없으면 503.
 */
export async function cancelCampaignClient(id: string): Promise<CancelResult> {
  const res = await apiSend(`/api/campaigns/${encodeURIComponent(id)}/cancel`, {
    method: 'POST',
  });
  return parse<CancelResult>(res);
}

/**
 * 수신자 CSV 다운로드 URL. 브라우저 <a download> 로 사용.
 *   status: fail/ok/undefined(=전체).
 */
export function buildCampaignExportHref(
  id: string,
  options: { status?: 'fail' | 'ok' } = {},
): string {
  const qs = options.status ? `?status=${options.status}` : '';
  return `/api/campaigns/${encodeURIComponent(id)}/export.csv${qs}`;
}

export type UploadedAttachment = {
  attachmentId: number;
  width: number;
  height: number;
  sizeBytes: number;
  originalFilename: string;
  /** <img src> 용 */
  url: string;
};

/**
 * MMS 첨부 이미지 업로드 — 서버 전처리 후 msghub 업로드 + DB BLOB 저장.
 * 성공 시 attachmentId + 미리보기 URL 반환.
 */
export async function uploadCampaignAttachmentClient(
  file: File,
): Promise<UploadedAttachment> {
  const form = new FormData();
  form.append('file', file);
  const res = await apiSend('/api/campaigns/attachments', {
    method: 'POST',
    body: form,
  });
  return parse<UploadedAttachment>(res);
}
