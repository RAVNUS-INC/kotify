import { Badge, type BadgeKind } from '@/components/ui';
import type { RecipientStatus } from '@/types/campaign';

const MAP: Record<RecipientStatus, { label: string; kind: BadgeKind; dot?: boolean }> = {
  queued: { label: '대기', kind: 'neutral' },
  delivered: { label: '도달', kind: 'success', dot: true },
  read: { label: '읽음', kind: 'success', dot: true },
  replied: { label: '회신', kind: 'brand', dot: true },
  failed: { label: '실패', kind: 'danger', dot: true },
  fallback_sms: { label: 'SMS 대체', kind: 'warning' },
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
