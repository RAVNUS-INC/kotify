'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Button, Icon } from '@/components/ui';
import {
  buildCampaignExportHref,
  cancelCampaignClient,
} from '@/lib/campaigns-client';

export type CampaignDetailActionsProps = {
  campaignId: string;
  status: string;
  canCancel: boolean;
};

/**
 * 캠페인 상세 상단 액션 — 목록 링크 + 수신자 CSV 다운로드 + 예약 취소.
 *
 * - 목록 링크는 항상 노출.
 * - CSV 다운로드는 viewer 이상 모두 허용 (백엔드 router-level require_user).
 * - 취소 버튼은 canCancel=true AND status in {scheduled} 일 때만 (그외엔
 *   백엔드가 400).
 */
export function CampaignDetailActions({
  campaignId,
  status,
  canCancel,
}: CampaignDetailActionsProps) {
  const router = useRouter();
  const [canceling, setCanceling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // status 매핑: backend 'cancelled' = 취소완료, 'scheduled' = 예약됨
  const showCancelButton = canCancel && status === 'scheduled';

  const onCancel = async () => {
    if (canceling) return;
    if (!confirm('이 예약을 취소하시겠습니까?')) return;
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
