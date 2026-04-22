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

/**
 * msghub 인바운드 웹훅 진단 정보. 2개 엔드포인트(report / mo) 의 URL 과
 * "작동 중인가?" 상태를 한 눈에 보여준다.
 */
export type WebhookStatus = 'not_configured' | 'never_received' | 'stale' | 'ok';

export type Webhook = {
  id: string;
  name: string;
  description: string;
  /** msghub 콘솔에 등록할 전체 URL. `not_configured` 면 빈 문자열. */
  url: string;
  configured: boolean;
  status: WebhookStatus;
  /** "YYYY-MM-DD HH:MM" KST. 여태 수신 이력 없으면 null. */
  lastReceivedAt?: string | null;
};

export type WebhookListMeta = {
  total: number;
  /** 설정 누락 시 무엇을 고치라는 한 줄 힌트. */
  hint?: string | null;
  outbound?: {
    featurePending: boolean;
    note: string;
  };
};
