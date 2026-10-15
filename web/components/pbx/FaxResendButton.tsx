'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button, Icon, useConfirm } from '@/components/ui';
import { formatPhone } from '@/lib/phone';
import { resendFaxClient } from '@/lib/pbx-client';
import type { FaxJob } from '@/types/pbx';

/**
 * 실패·확인 필요 팩스를 같은 PDF·번호로 새 작업으로 보낸다. `확인 필요`는 이미 전송됐을
 * 수도 있어 확인 대화상자로 중복 발송 가능성을 알린다. 자동 재발송은 하지 않는다.
 */
export function FaxResendButton({ job }: { job: FaxJob }) {
  const router = useRouter();
  const { confirm, dialog } = useConfirm();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onClick = async () => {
    if (busy) return;
    const ok = await confirm({
      title: '팩스를 다시 보낼까요?',
      description:
        job.status === 'UNKNOWN'
          ? `${formatPhone(job.recipient)} 로 이미 전송됐을 수 있습니다. PBX 팩스 뷰어에서 확인한 뒤 다시 보내세요.`
          : `${formatPhone(job.recipient)} 로 같은 PDF 를 다시 보냅니다.`,
      confirmLabel: '다시 보내기',
    });
    if (!ok) return;
    setBusy(true);
    setError(null);
    try {
      await resendFaxClient(job.id);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : '다시 보내기 실패');
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
        다시 보내기
      </Button>
      {error ? (
        <span role="alert" className="text-[12px] text-danger">
          {error}
        </span>
      ) : null}
      {dialog}
    </div>
  );
}
