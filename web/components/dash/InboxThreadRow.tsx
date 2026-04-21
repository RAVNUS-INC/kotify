import type { InboxThread } from '@/types/dashboard';
import { cn } from '@/lib/cn';

export type InboxThreadRowProps = {
  thread: InboxThread;
};

export function InboxThreadRow({ thread }: InboxThreadRowProps) {
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
            {thread.name}
            {unread && <span className="sr-only"> — 읽지 않음</span>}
          </div>
          <div className="shrink-0 font-mono text-[11px] text-ink-dim">
            {thread.time}
          </div>
        </div>
        <div className="truncate text-[12.5px] text-ink-muted">
          {thread.preview}
        </div>
      </div>
    </li>
  );
}
