export type NotificationKind = 'send_result' | 'system' | 'security' | 'billing';
export type NotificationLevel = 'success' | 'info' | 'warning' | 'error';

export type Notification = {
  id: string;
  kind: NotificationKind;
  level: NotificationLevel;
  title: string;
  subtitle?: string;
  /** "YYYY-MM-DD HH:MM" */
  createdAt: string;
  unread?: boolean;
  /** 클릭 시 이동할 내부 경로. 없으면 클릭 안 됨 */
  href?: string;
};

export type NotificationListMeta = {
  total: number;
  unreadTotal: number;
};
