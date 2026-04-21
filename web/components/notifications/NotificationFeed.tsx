'use client';

import type { Notification } from '@/types/notification';
import { Stagger } from '@/components/motion';
import { EmptyState } from '@/components/ui';
import { NotificationItem } from './NotificationItem';

export type NotificationFeedProps = {
  items: ReadonlyArray<Notification>;
};

export function NotificationFeed({ items }: NotificationFeedProps) {
  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-line bg-surface">
        <EmptyState
          icon="bell"
          title="알림 없음"
          description="현재 필터에 맞는 알림이 없습니다."
          size="md"
        />
      </div>
    );
  }

  // 10개 이상은 step=40, 미만이면 60 (motion.md 기준)
  const step = items.length >= 10 ? 40 : 60;

  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface">
      <Stagger step={step} y={8} duration={400}>
        {items.map((n) => (
          <NotificationItem key={n.id} notification={n} />
        ))}
      </Stagger>
    </div>
  );
}
