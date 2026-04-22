/**
 * Notifications — client-side helpers.
 *
 * server-side 코드(`lib/notifications.ts`)는 `next/headers` 의존성 때문에
 * 클라이언트 번들에 포함될 수 없다. 클라이언트 컴포넌트에서 쓰는 POST 호출
 * helpers 는 이 파일에서 별도로 export 한다.
 *
 * mutating 요청은 apiSend 로 — X-CSRF-Token 자동 첨부.
 */

import { apiSend } from './csrf-client';

export async function markNotificationReadClient(id: string): Promise<void> {
  await apiSend(`/api/notifications/${encodeURIComponent(id)}/read`, {
    method: 'POST',
  });
}

export async function markAllNotificationsReadClient(): Promise<number> {
  const res = await apiSend('/api/notifications/read-all', { method: 'POST' });
  const body = (await res.json()) as { data?: { readCount: number } };
  return body.data?.readCount ?? 0;
}
