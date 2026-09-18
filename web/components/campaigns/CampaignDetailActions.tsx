'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Button, Icon, useConfirm } from '@/components/ui';
import {
  buildCampaignExportHref,
  cancelCampaignClient,
} from '@/lib/campaigns-client';

export type CampaignDetailActionsProps = {
  campaignId: string;
  canCancel: boolean;
  canCancelReservation: boolean;
};

/**
 * 캠페인 상세 상단 액션 — 목록 링크 + 수신자 CSV 다운로드 + 예약 취소.
 *
 * - 목록 링크는 항상 노출.
 * - CSV 다운로드는 viewer 이상 모두 허용 (백엔드 router-level require_user).
 * - 취소 권한이 있고 서버가 취소할 예약이 남았다고 응답하면 취소 버튼을 노출한다.
 *   일부 청크 요청이 실패한 캠페인도 접수된 예약은 취소할 수 있다.
 */
export function CampaignDetailActions({
  campaignId,
  canCancel,
  canCancelReservation,
}: CampaignDetailActionsProps) {
  const router = useRouter();
  const [canceling, setCanceling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { confirm, dialog } = useConfirm();

  const showCancelButton = canCancel && canCancelReservation;

  const onCancel = async () => {
    if (canceling) return;
    if (
      !(await confirm({
        title: '예약 취소',
        description: '이 예약을 취소하시겠습니까?',
        tone: 'danger',
        confirmLabel: '예약 취소',
      }))
    )
      return;
    setCanceling(true);
    setError(null);
    try {
      const r = await cancelCampaignClient(campaignId);
      // 정보성 메시지. 예약이 이미 처리된 경우도 서버가 200 으로 안내.
      if (r.message && r.status !== 'cancelled') {
        setError(null);
        alert(r.message);
      }
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : '취소 실패');
    } finally {
      setCanceling(false);
    }
  };

  return (
    <div className="flex flex-col items-end gap-1">
      {dialog}
      <div className="flex items-center gap-2">
        <Link
          href="/campaigns"
          className="inline-flex h-8 items-center gap-1 rounded border border-gray-4 bg-surface px-2.5 text-sm text-ink-muted transition-colors duration-fast ease-out hover:bg-gray-1"
        >
          <Icon name="arrowLeft" size={12} />
          목록
        </Link>
        <a
          href={buildCampaignExportHref(campaignId)}
          className="inline-flex h-8 items-center gap-1 rounded border border-gray-4 bg-surface px-2.5 text-sm text-ink transition-colors duration-fast ease-out hover:bg-gray-1"
          download
        >
          <Icon name="download" size={12} />
          수신자 CSV
        </a>
        {showCancelButton ? (
          <Button
            variant="danger"
            size="sm"
            icon={<Icon name="x" size={12} />}
            onClick={onCancel}
            loading={canceling}
          >
            예약 취소
          </Button>
        ) : null}
      </div>
      {error ? (
        <span className="text-[11px] text-danger" role="alert">
          {error}
        </span>
      ) : null}
    </div>
  );
}
