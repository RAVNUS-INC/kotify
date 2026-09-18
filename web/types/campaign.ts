export type CampaignStatus =
  | 'draft'
  | 'scheduled'
  | 'sending'
  | 'sent'
  | 'failed'
  | 'cancelled';

export type CampaignChannel = 'rcs' | 'sms' | 'lms' | 'mms' | 'kakao';

export type Campaign = {
  id: string;
  name: string;
  status: CampaignStatus;
  sender: string;
  channel: CampaignChannel;
  /** "YYYY-MM-DD HH:MM" (mock) */
  createdAt: string;
  scheduledAt?: string;
  recipients: number;
  reach: number | null;
  replies: number | null;
  cost: number;
  failureReason?: string;
};

export type CampaignListMeta = {
  total: number;
  cursor?: string;
};

export type RecipientStatus =
  | 'queued'
  | 'delivered'
  | 'read'
  | 'replied'
  | 'failed'
  | 'fallback_sms'
  /** 예약 취소로 발송되지 않음. */
  | 'cancelled';

export type Recipient = {
  id: string;
  name: string;
  phone: string;
  status: RecipientStatus;
  sentAt?: string | null;
  readAt?: string;
  repliedAt?: string;
  failureReason?: string;
};

export type CampaignBreakdown = {
  total: number;
  rcsDelivered: number;
  smsFallback: number;
  failed: number;
  replies: number;
};

export type CampaignDetail = Campaign & {
  /** 일부 요청이 실패했어도 취소할 수 있는 예약 청크가 남아 있음. 권한 검사는 별도. */
  canCancelReservation: boolean;
  recipientsSample: Recipient[];
  breakdown: CampaignBreakdown;
};
