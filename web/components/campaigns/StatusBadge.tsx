import { Badge, type BadgeKind } from '@/components/ui';
import type { CampaignStatus } from '@/types/campaign';

const STATUS_MAP: Record<CampaignStatus, { label: string; kind: BadgeKind; dot?: boolean }> = {
  draft: { label: '초안', kind: 'neutral' },
  scheduled: { label: '예약', kind: 'info', dot: true },
  sending: { label: '진행', kind: 'brand', dot: true },
  sent: { label: '완료', kind: 'success', dot: true },
  failed: { label: '실패', kind: 'danger', dot: true },
  cancelled: { label: '취소', kind: 'warning' },
};

export type StatusBadgeProps = {
  status: CampaignStatus;
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const { label, kind, dot } = STATUS_MAP[status];
  return (
    <Badge kind={kind} dot={dot}>
      {label}
    </Badge>
  );
}
