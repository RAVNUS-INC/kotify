import { apiSend } from './csrf-client';

export type CampaignPreviewInput = {
  message: string;
  recipients: string[];
  sendChannel: 'rcs' | 'sms';
  hasAttachment: boolean;
};

export type CampaignPreview = {
  byteLength: number | null;
  maxBytes: number;
  valid: boolean;
  error: string | null;
  recipientCount: number;
  channel: 'SMS' | 'LMS' | 'MMS' | null;
  costMin: number | null;
  costMax: number | null;
};

const nonnegativeInteger = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;

/** DB 변경이나 공급자 발송 없이 실제 서버 기준의 길이·예상 비용을 조회한다. */
export async function previewCampaignClient(
  input: CampaignPreviewInput,
  signal?: AbortSignal,
): Promise<CampaignPreview> {
  const response = await apiSend('/api/campaigns/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
    signal,
  });
  let body: {
    data?: CampaignPreview;
    error?: { message?: string };
    detail?: { message?: string };
  };
  try {
    body = await response.json();
  } catch {
    throw new Error(`견적 응답을 읽지 못했습니다 (HTTP ${response.status})`);
  }
  if (!body || typeof body !== 'object') throw new Error('견적 응답이 올바르지 않습니다');
  if (!response.ok || body.error) {
    throw new Error(body.error?.message ?? body.detail?.message ?? `HTTP ${response.status}`);
  }
  const result = body.data;
  if (
    !result ||
    (result.byteLength !== null && !nonnegativeInteger(result.byteLength)) ||
    !nonnegativeInteger(result.maxBytes) || result.maxBytes === 0 ||
    !nonnegativeInteger(result.recipientCount) ||
    typeof result.valid !== 'boolean' ||
    (result.error !== null && typeof result.error !== 'string') ||
    ![null, 'SMS', 'LMS', 'MMS'].includes(result.channel) ||
    (result.costMin !== null && !nonnegativeInteger(result.costMin)) ||
    (result.costMax !== null && !nonnegativeInteger(result.costMax)) ||
    ((result.costMin === null) !== (result.costMax === null)) ||
    (result.costMin !== null && result.costMax !== null && result.costMin > result.costMax) ||
    (result.valid && (
      result.byteLength === null || result.byteLength > result.maxBytes ||
      result.error !== null || !result.channel || !result.recipientCount ||
      result.costMin === null || result.costMax === null
    ))
  ) {
    throw new Error('견적 응답이 올바르지 않습니다');
  }
  return result;
}
