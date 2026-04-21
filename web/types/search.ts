import type { Contact } from './contact';

export type SearchThread = {
  id: string;
  name: string;
  phone: string;
  snippet: string;
  time: string;
  campaignName?: string | null;
};

export type SearchCampaign = {
  id: string;
  name: string;
  status: string;
  createdAt: string;
};

export type SearchAudit = {
  id: string;
  time: string;
  actor: string;
  action: string;
  target: string;
};

export type SearchCounts = {
  total: number;
  contacts: number;
  threads: number;
  campaigns: number;
  auditLogs: number;
};

export type SearchResult = {
  contacts: Contact[];
  threads: SearchThread[];
  campaigns: SearchCampaign[];
  auditLogs: SearchAudit[];
  counts: SearchCounts;
};

export type SearchSection = 'all' | 'contacts' | 'threads' | 'campaigns' | 'audit';
