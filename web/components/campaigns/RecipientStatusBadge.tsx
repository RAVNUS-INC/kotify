import { Badge, type BadgeKind } from '@/components/ui';
import type { RecipientStatus } from '@/types/campaign';

const MAP: Record<RecipientStatus, { label: string; kind: BadgeKind; dot?: boolean }> = {
  queued: { label: '대기', kind: 'neutral' },
  delivered: { label: '도달', kind: 'success', dot: true },
  read: { label: '읽음', kind: 'success', dot: true },
  replied: { label: '회신', kind: 'brand', dot: true },
  failed: { label: '실패', kind: 'danger', dot: true },
  fallback_sms: { label: 'SMS 대체', kind: 'warning' },
  // 캠페인 상태 배지(StatusBadge)의 취소와 같은 모양 — 같은 화면에서 한 가지로 읽히게.
  cancelled: { label: '취소', kind: 'warning' },
};

export type RecipientStatusBadgeProps = {
  status: RecipientStatus;
};

export function RecipientStatusBadge({ status }: RecipientStatusBadgeProps) {
  const { label, kind, dot } = MAP[status];
  return (
    <Badge kind={kind} dot={dot}>
      {label}
    </Badge>
  );
}
