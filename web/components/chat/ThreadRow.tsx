import Link from 'next/link';
import type { Route } from 'next';
import type { ChatThread } from '@/types/chat';
import { formatThreadTime } from '@/lib/chat';
import { cn } from '@/lib/cn';
import { hasDisplayName, threadDisplayName } from '@/lib/phone';
import { Icon } from '@/components/ui';

export type ThreadRowProps = {
  thread: ChatThread;
  /** "YYYY-MM-DD" (KST) — 목록 응답의 meta.today. 시각 문구(오늘·어제·날짜)의 기준일. */
  today: string;
  active?: boolean;
  href: Route;
};

const CHANNEL_LABEL: Record<ChatThread['channel'], string> = {
  sms: 'SMS',
  lms: 'LMS',
  mms: 'MMS',
  rcs: 'RCS',
  kakao: 'KAKAO',
};

export function ThreadRow({ thread, today, active = false, href }: ThreadRowProps) {
  const unread = !!thread.unread;
  return (
    <Link
      href={href}
      aria-current={active ? 'true' : undefined}
      className={cn(
        'flex items-start gap-3 border-b border-line px-4 py-3 text-inherit no-underline transition-colors duration-fast ease-out',
        // 열린 대화: 연보라 바탕 + 왼쪽 3px 브랜드 선(색만이 아니라 aria-current 로도 알린다)
        active ? 'bg-brand-soft shadow-[inset_3px_0_0_var(--brand)]' : 'bg-surface hover:bg-surface-subtle',
      )}
    >
      {unread && (
        <span
          aria-hidden
          className="mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-brand"
        />
      )}
      {!unread && <span aria-hidden className="mt-1 inline-block h-1.5 w-1.5 shrink-0" />}

      {/* 이름이 있으면 첫 글자, 번호뿐이면 사람 아이콘 — 예전엔 번호 첫 글자 "0" 이 보였다 */}
      <div
        aria-hidden
        className={cn(
          'flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-md font-bold',
          hasDisplayName(thread) ? 'bg-brand-soft text-brand' : 'bg-surface-hover text-ink-dim',
        )}
      >
        {hasDisplayName(thread) ? threadDisplayName(thread).charAt(0) : <Icon name="user" size={16} />}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span
            className={cn(
              'truncate text-base',
              unread ? 'font-semibold text-ink' : 'text-ink',
            )}
          >
            {threadDisplayName(thread)}
            {unread && <span className="sr-only"> — 읽지 않음</span>}
          </span>
          <span className="shrink-0 tabular-nums text-xs text-ink-dim">
            {formatThreadTime(thread, today)}
          </span>
        </div>
        <div className="flex items-center gap-1.5 text-md">
          <span
            className={cn(
              'shrink-0 text-xs',
              thread.channel === 'rcs' ? 'text-brand' : 'text-ink-dim',
            )}
          >
            {CHANNEL_LABEL[thread.channel]}
          </span>
          <span className="truncate text-ink-muted">{thread.preview}</span>
        </div>
      </div>
    </Link>
  );
}
