import Link from 'next/link';
import type { Route } from 'next';
import type { InboxThread } from '@/types/dashboard';
import { formatThreadTime } from '@/lib/chat';
import { cn } from '@/lib/cn';
import { formatPhone } from '@/lib/phone';

export type InboxThreadRowProps = {
  thread: InboxThread;
  /** "YYYY-MM-DD" (KST) — 대시보드 응답의 inbox.today. 시각 문구의 기준일. */
  today: string;
};

export function InboxThreadRow({ thread, today }: InboxThreadRowProps) {
  const unread = !!thread.unread;
  return (
    <li>
      {/* 행 전체가 그 대화방으로 가는 링크 — 예전에는 눌러도 아무 일이 없었다 */}
      <Link
        href={`/chat/${encodeURIComponent(thread.id)}` as Route}
        className={cn(
          'flex items-center gap-3 px-5 py-3 text-inherit no-underline transition-colors duration-fast hover:bg-surface-subtle',
          unread && 'bg-brand-soft/30',
        )}
      >
        <span
          aria-hidden
          className={cn(
            'inline-block h-1.5 w-1.5 shrink-0 rounded-full',
            unread ? 'bg-brand' : 'bg-transparent',
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <div
              className={cn(
                'truncate text-base',
                unread ? 'font-semibold text-ink' : 'text-ink-muted',
              )}
            >
              {thread.phone && thread.name === thread.phone
                ? formatPhone(thread.phone)
                : thread.name}
              {unread && <span className="sr-only"> — 읽지 않음</span>}
            </div>
            <div className="shrink-0 text-xs tabular-nums text-ink-dim">
              {formatThreadTime(thread, today)}
            </div>
          </div>
          <div className="truncate text-md text-ink-muted">{thread.preview}</div>
        </div>
      </Link>
    </li>
  );
}
