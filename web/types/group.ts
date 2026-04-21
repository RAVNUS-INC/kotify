import type { Contact } from './contact';

export type GroupSource = 'ad' | 'csv' | 'api' | 'manual';

export type Group = {
  id: string;
  name: string;
  description?: string;
  source: GroupSource;
  memberCount: number;
  validCount: number;
  lastSyncAt?: string | null;
  lastCampaignAt?: string | null;
  /** 0-100, 없으면 null/undefined */
  reachRate?: number | null;
};

export type GroupDetail = Group & {
  members: Contact[];
};
