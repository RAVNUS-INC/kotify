import { Badge, type BadgeKind } from '@/components/ui';
import type { NumberStatus } from '@/types/number';

const MAP: Record<NumberStatus, { label: string; kind: BadgeKind; dot?: boolean }> = {
  approved: { label: '승인', kind: 'success', dot: true },
  pending: { label: '대기', kind: 'warning', dot: true },
  rejected: { label: '반려', kind: 'danger', dot: true },
  expired: { label: '만료', kind: 'neutral' },
};

export type NumberStatusBadgeProps = {
  status: NumberStatus;
  reason?: string;
};

export function NumberStatusBadge({ status, reason }: NumberStatusBadgeProps) {
  const { label, kind, dot } = MAP[status];
  return (
    <span title={reason}>
      <Badge kind={kind} dot={dot}>
        {label}
      </Badge>
    </span>
  );
}
