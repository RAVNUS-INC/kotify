export type Contact = {
  id: string;
  name: string;
  phone: string;
  email?: string;
  team?: string;
  tags?: string[];
  groupIds?: string[];
  lastCampaign?: string | null;
  createdAt?: string;
};

export type ContactReplyEntry = {
  id: string;
  campaignName: string;
  text: string;
  at: string;
};

export type ContactRecentCampaign = {
  id: string;
  name: string;
  status: string;
  sentAt: string;
};

export type ContactDetail = Contact & {
  recentCampaigns?: ContactRecentCampaign[];
  replyHistory?: ContactReplyEntry[];
};
