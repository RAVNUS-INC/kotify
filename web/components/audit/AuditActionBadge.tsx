import { Badge, type BadgeKind } from '@/components/ui';

/**
 * action 문자열 → 톤 매핑.
 * 보안·실패성 액션은 danger, 파괴적 액션은 warning, 중립은 neutral.
 */
function toneOf(action: string): BadgeKind {
  const a = action.toUpperCase();
  if (a.includes('FAILED') || a.includes('REJECT') || a.includes('LOGIN_FAILED')) {
    return 'danger';
  }
  if (
    a.includes('DELETE') ||
    a.includes('DEACTIVATE') ||
    a.includes('CANCEL') ||
    a.includes('REVOKE')
  ) {
    return 'warning';
  }
  if (a.includes('CREATE') || a.includes('REGISTER') || a.includes('INVITE')) {
    return 'success';
  }
  if (a.includes('PATCH') || a.includes('UPDATE') || a.includes('UPLOAD')) {
    return 'brand';
  }
  return 'neutral';
}

export type AuditActionBadgeProps = {
  action: string;
};

export function AuditActionBadge({ action }: AuditActionBadgeProps) {
  return <Badge kind={toneOf(action)}>{action}</Badge>;
}
