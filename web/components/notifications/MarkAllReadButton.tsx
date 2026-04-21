'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button, Icon } from '@/components/ui';
import { markAllNotificationsReadClient } from '@/lib/notifications';

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
