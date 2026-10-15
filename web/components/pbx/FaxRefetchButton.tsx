'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button, Icon } from '@/components/ui';
import { refetchInboxClient } from '@/lib/pbx-client';

/** PBX 에서 받은 팩스 PDF 를 다시 가져온다 (관리자). */
export function FaxRefetchButton({ id }: { id: number }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onClick = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await refetchInboxClient(id);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : '다시 가져오기 실패');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col items-end gap-0.5">
      <Button
        type="button"
        variant="secondary"
        size="sm"
        onClick={onClick}
        loading={busy}
        icon={<Icon name="refresh" size={12} />}
      >
        다시 가져오기
      </Button>
      {error ? (
        <span role="alert" className="text-sm text-danger">
          {error}
        </span>
      ) : null}
    </div>
  );
}
