export type Role = 'owner' | 'admin' | 'operator' | 'viewer';

export type Org = {
  name: string;
  service: string;
  contact: string;
  timezone: string;
  limits: {
    recipientsPerCampaign: number;
    campaignsPerMinute: number;
  };
};

export type Member = {
  id: string;
  email: string;
  name: string;
  role: Role;
  active: boolean;
  invitedAt: string;
};

export type ApiKey = {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  createdAt: string;
  lastUsedAt?: string | null;
};

export type Webhook = {
  id: string;
  url: string;
  events: string[];
  active: boolean;
  createdAt: string;
};
