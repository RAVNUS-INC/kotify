import { apiSend } from './csrf-client';

export type ReplyValidation = {
  byteLength: number | null;
  maxBytes: number;
  valid: boolean;
  error: string | null;
};

/** 발송과 같은 서버 인코딩 규칙으로 확인한다. 메시지를 발송하는 요청이 아니다. */
export async function validateReplyClient(
  text: string,
  signal?: AbortSignal,
): Promise<ReplyValidation> {
  const response = await apiSend('/api/threads/validate-reply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
    signal,
  });
  let body: {
    data?: ReplyValidation;
    error?: { message?: string };
    detail?: { message?: string };
  };
  try {
    body = await response.json();
  } catch {
    throw new Error(`길이 확인 응답을 읽지 못했습니다 (HTTP ${response.status})`);
  }
  if (!body || typeof body !== 'object') {
    throw new Error('길이 확인 응답이 올바르지 않습니다');
  }
  if (!response.ok || body.error) {
    throw new Error(body.error?.message ?? body.detail?.message ?? `HTTP ${response.status}`);
  }
  const result = body.data;
  if (
    !result ||
    (result.byteLength !== null &&
      (!Number.isInteger(result.byteLength) || result.byteLength < 0)) ||
    !Number.isInteger(result.maxBytes) || result.maxBytes <= 0 ||
    typeof result.valid !== 'boolean' ||
    (result.error !== null && typeof result.error !== 'string') ||
    (result.valid && (
      result.byteLength === null || result.byteLength > result.maxBytes || result.error !== null
    ))
  ) {
    throw new Error('길이 확인 응답이 올바르지 않습니다');
  }
  return result;
}
