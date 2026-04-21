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
