import { apiFetch, type ApiEnvelope } from './api';
import type { Notification, NotificationListMeta } from '@/types/notification';

export type FetchNotificationsParams = {
  kind?: string;
  unread?: boolean;
};

export type NotificationListResult = {
  items: Notification[];
  meta: NotificationListMeta;
};

/**
 * Server-only — meta까지 함께 반환하려면 envelope을 직접 다뤄야 한다.
 * apiFetch는 data만 뽑는 일반 헬퍼라 여기선 fetch를 직접 호출.
 */
export async function fetchNotifications(
  params: FetchNotificationsParams = {},
): Promise<NotificationListResult> {
  const qs = new URLSearchParams();
  if (params.kind && params.kind !== 'all') qs.set('kind', params.kind);
  if (params.unread) qs.set('unread', 'true');
  const suffix = qs.toString() ? `?${qs.toString()}` : '';

  const FASTAPI_URL = process.env.FASTAPI_URL ?? 'http://127.0.0.1:8080';
  const res = await fetch(`${FASTAPI_URL}/notifications${suffix}`, {
    cache: 'no-store',
  });
  const body = (await res.json()) as ApiEnvelope<Notification[]> & {
    meta?: NotificationListMeta;
  };
  if (!res.ok || body.error || !body.data) {
    throw new Error(body.error?.message ?? `HTTP ${res.status}`);
  }
  return {
    items: body.data,
    meta: (body.meta ?? { total: body.data.length, unreadTotal: 0 }) as NotificationListMeta,
  };
}

export async function markNotificationReadClient(id: string): Promise<void> {
  await fetch(`/api/notifications/${encodeURIComponent(id)}/read`, {
    method: 'POST',
  });
}

export async function markAllNotificationsReadClient(): Promise<number> {
  const res = await fetch('/api/notifications/read-all', { method: 'POST' });
  const body = (await res.json()) as { data?: { readCount: number } };
  return body.data?.readCount ?? 0;
}
