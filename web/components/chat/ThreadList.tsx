import type { Route } from 'next';
import type { ChatThread } from '@/types/chat';
import { EmptyState } from '@/components/ui';
import type { ChatFilter } from './ChatFilters';
import { ThreadRow } from './ThreadRow';

export type ThreadListProps = {
  threads: ReadonlyArray<ChatThread>;
  activeId?: string;
  filter: ChatFilter;
};

function buildHref(threadId: string, filter: ChatFilter): Route {
  const qs = new URLSearchParams();
  qs.set('selected', threadId);
  if (filter !== 'all') qs.set('filter', filter);
  return `/chat?${qs.toString()}` as Route;
}

export function ThreadList({ threads, activeId, filter }: ThreadListProps) {
  return (
    <div
      aria-label="대화 목록"
      className="flex flex-col overflow-y-auto border-r border-line"
    >
      <div className="sticky top-0 flex items-center justify-between border-b border-line bg-surface px-4 py-2">
        <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-ink-dim">
          {threads.length}개 대화
        </span>
      </div>

      {threads.length === 0 ? (
        <EmptyState
          icon="inbox"
          title="대화 없음"
          description={
            filter === 'unread'
              ? '읽지 않은 대화가 없습니다.'
              : '수신된 답장이 아직 없습니다.'
          }
          size="sm"
        />
      ) : (
        <ul className="flex flex-col">
          {threads.map((t) => (
            <li key={t.id}>
              <ThreadRow
                thread={t}
                active={t.id === activeId}
                href={buildHref(t.id, filter)}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
