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
  // apiFetch 와 동일: 서버 컴포넌트에서 FastAPI 로 세션 쿠키 수동 forward 필요.
  // 동적 import 로 client bundle 에 next/headers 가 포함되지 않도록 한다.
  let cookieHeader = '';
  try {
    const { cookies } = await import('next/headers');
    cookieHeader = cookies().toString();
  } catch {
    /* noop */
  }
  const res = await fetch(`${FASTAPI_URL}/notifications${suffix}`, {
    cache: 'no-store',
    headers: cookieHeader ? { cookie: cookieHeader } : undefined,
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

// 클라이언트 전용 헬퍼는 `./notifications-client.ts` 로 분리.
// (이 파일은 next/headers 를 import 하므로 client component 에서 직접 import 시
//  webpack 빌드가 깨진다. server/client 경계 분리.)
