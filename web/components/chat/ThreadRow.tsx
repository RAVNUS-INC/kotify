import Link from 'next/link';
import type { Route } from 'next';
import type { ChatThread } from '@/types/chat';
import { cn } from '@/lib/cn';

export type ThreadRowProps = {
  thread: ChatThread;
  active?: boolean;
  href: Route;
};

const CHANNEL_LABEL: Record<ChatThread['channel'], string> = {
  sms: 'SMS',
  rcs: 'RCS',
  kakao: 'KAKAO',
};

export function ThreadRow({ thread, active = false, href }: ThreadRowProps) {
  const unread = !!thread.unread;
  return (
    <Link
      href={href}
      aria-current={active ? 'true' : undefined}
      className={cn(
        'flex items-start gap-3 border-b border-line px-4 py-3 transition-colors duration-fast ease-out',
        active ? 'bg-brand-soft' : unread ? 'bg-surface hover:bg-gray-1' : 'bg-surface hover:bg-gray-1',
      )}
    >
      {unread && (
        <span
          aria-hidden
          className="mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-brand"
        />
      )}
      {!unread && <span aria-hidden className="mt-1 inline-block h-1.5 w-1.5 shrink-0" />}

      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-3 font-mono text-[11px] text-gray-9">
        {thread.name.charAt(0)}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span
            className={cn(
              'truncate text-[13.5px]',
              unread ? 'font-semibold text-ink' : 'text-ink',
            )}
          >
            {thread.name}
            {unread && <span className="sr-only"> — 읽지 않음</span>}
          </span>
          <span className="shrink-0 font-mono text-[11px] text-ink-dim">
            {thread.time}
          </span>
        </div>
        <div className="flex items-center gap-1.5 text-[12.5px]">
          <span
            className={cn(
              'shrink-0 font-mono text-[10px]',
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
