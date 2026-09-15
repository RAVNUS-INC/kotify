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
  recipientsSample: Recipient[];
  breakdown: CampaignBreakdown;
};
