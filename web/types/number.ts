export type NumberKind = 'rep' | 'mobile';
export type NumberStatus = 'approved' | 'pending' | 'rejected' | 'expired';
export type NumberSupport = 'rcs' | 'sms' | 'lms' | 'mms';

export type SenderNumber = {
  id: string;
  number: string;
  kind: NumberKind;
  supports: NumberSupport[];
  brand: string;
  status: NumberStatus;
  dailyUsage: number;
  dailyLimit?: number | null;
  registeredAt: string;
  failureReason?: string;
};
