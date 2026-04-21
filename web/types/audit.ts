export type AuditEntry = {
  id: string;
  /** "YYYY-MM-DD HH:MM:SS" */
  time: string;
  actor: string;
  actorEmail: string;
  /** 예: LOGIN, CREATE_CAMPAIGN, PATCH_ORG, CAMPAIGN_FAILED ... */
  action: string;
  target: string;
  ip: string;
};
