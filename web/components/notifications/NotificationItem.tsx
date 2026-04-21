import Link from 'next/link';
import type { Route } from 'next';
import type { Notification, NotificationLevel } from '@/types/notification';
import { Icon, type IconName } from '@/components/ui';
import { cn } from '@/lib/cn';
import { safeInternalHref } from '@/lib/url';

export type NotificationItemProps = {
  notification: Notification;
};

const LEVEL_ICON: Record<NotificationLevel, IconName> = {
  success: 'check',
  info: 'info',
  warning: 'alert',
  error: 'error',
};

const LEVEL_BG: Record<NotificationLevel, string> = {
  success: 'bg-success-bg text-success',
  info: 'bg-info-bg text-info',
  warning: 'bg-warning-bg text-warning',
  error: 'bg-danger-bg text-danger',
};

export function NotificationItem({ notification: n }: NotificationItemProps) {
  const content = (
    <div
      className={cn(
        'relative flex items-start gap-3 px-5 py-3 transition-colors duration-fast ease-out',
        n.unread ? 'bg-brand-soft/30' : 'bg-surface hover:bg-gray-1',
      )}
    >
      {/* unread 좌 레일 (2px brand) */}
      {n.unread && (
        <span
          aria-hidden
          className="absolute left-0 top-0 h-full w-[2px] bg-brand"
        />
      )}

      <div
        aria-hidden
        className={cn(
          'flex h-9 w-9 shrink-0 items-center justify-center rounded-full',
          LEVEL_BG[n.level],
        )}
      >
        <Icon name={LEVEL_ICON[n.level]} size={14} strokeWidth={1.8} />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span
            className={cn(
              'truncate text-sm',
              n.unread ? 'font-semibold text-ink' : 'font-medium text-ink-muted',
            )}
          >
            {n.title}
            {n.unread && <span className="sr-only"> — 읽지 않음</span>}
          </span>
          <span className="shrink-0 font-mono text-[11px] text-ink-dim">
            {n.createdAt.split(' ')[1] ?? n.createdAt}
          </span>
        </div>
        {n.subtitle && (
          <div className="mt-0.5 truncate text-[12.5px] text-ink-muted">
            {n.subtitle}
          </div>
        )}
      </div>

      {n.href && (
        <Icon
          name="chevronRight"
          size={12}
          className="shrink-0 self-center text-ink-dim"
        />
      )}
    </div>
  );

  // open redirect 방어: 백엔드가 보낸 href 를 그대로 신뢰하지 않고
  // safeInternalHref 로 정규화한 뒤에만 Link 로 렌더한다.
  // 외부 스킴/protocol-relative/javascript: 는 전부 `/` 로 폴백.
  const safeHref = n.href ? safeInternalHref(n.href, '') : '';
  if (safeHref) {
    return (
      <Link
        href={safeHref as Route}
        aria-label={`${n.title} — ${n.subtitle ?? ''}`}
        className="block border-b border-line last:border-b-0 focus-visible:outline-none focus-visible:shadow-[0_0_0_3px_rgba(59,0,139,0.12)] focus-visible:z-10"
      >
        {content}
      </Link>
    );
  }

  return (
    <div className="border-b border-line last:border-b-0" role="listitem">
      {content}
    </div>
  );
}
