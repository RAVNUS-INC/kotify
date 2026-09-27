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
    <li
      className={cn(
        'flex items-center gap-3 px-5 py-3',
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
              'truncate text-[13.5px]',
              unread ? 'font-semibold text-ink' : 'text-ink-muted',
            )}
          >
            {thread.phone && thread.name === thread.phone ? formatPhone(thread.phone) : thread.name}
            {unread && <span className="sr-only"> — 읽지 않음</span>}
          </div>
          <div className="shrink-0 font-mono text-[11px] text-ink-dim">
            {formatThreadTime(thread, today)}
          </div>
        </div>
        <div className="truncate text-[12.5px] text-ink-muted">
          {thread.preview}
        </div>
      </div>
    </li>
  );
}
