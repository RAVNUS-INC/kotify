'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button, Icon } from '@/components/ui';
import { markAllNotificationsReadClient } from '@/lib/notifications-client';

export type MarkAllReadButtonProps = {
  disabled?: boolean;
};

export function MarkAllReadButton({ disabled }: MarkAllReadButtonProps) {
  const router = useRouter();
  const [pending, setPending] = useState(false);

  const onClick = async () => {
    if (pending || disabled) return;
    setPending(true);
    try {
      // 서버 mutation이 끝난 뒤 refresh를 트리거.
      // router.refresh()는 non-blocking이지만 mutation은 await로 완료 보장,
      // pending 재활성화 전까진 이중 클릭이 차단됨.
      await markAllNotificationsReadClient();
      router.refresh();
    } finally {
      setPending(false);
    }
  };

  return (
    <Button
      variant="secondary"
      size="sm"
      onClick={onClick}
      loading={pending}
      disabled={disabled || pending}
      icon={<Icon name="check" size={12} />}
    >
      모두 읽음
    </Button>
  );
}
