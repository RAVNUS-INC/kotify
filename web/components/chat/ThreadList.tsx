import type { Route } from 'next';
import Link from 'next/link';
import type { ChatThread, ChatThreadPageMeta } from '@/types/chat';
import { EmptyState } from '@/components/ui';
import type { ChatFilter } from './ChatFilters';
import { ThreadRow } from './ThreadRow';

export type ThreadListProps = {
  threads: ReadonlyArray<ChatThread>;
  activeId?: string;
  filter: ChatFilter;
  q?: string;
  page: ChatThreadPageMeta;
};

function buildHref(threadId: string | undefined, filter: ChatFilter, q: string, offset: number): Route {
  const qs = new URLSearchParams();
  if (threadId) qs.set('selected', threadId);
  if (filter !== 'all') qs.set('filter', filter);
  if (q) qs.set('q', q);
  if (offset > 0) qs.set('offset', String(offset));
  return `/chat?${qs.toString()}` as Route;
}

export function ThreadList({ threads, activeId, filter, q = '', page }: ThreadListProps) {
  return (
    <div
      aria-label="대화 목록"
      className="flex min-h-0 flex-col border-r border-line"
    >
      <div className="flex shrink-0 flex-col gap-2 border-b border-line bg-surface px-4 py-2">
        <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-ink-dim">
          {page.total}개 대화
        </span>
        <form action="/chat" method="get" className="flex gap-1">
          {activeId && <input type="hidden" name="selected" value={activeId} />}
          {filter !== 'all' && <input type="hidden" name="filter" value={filter} />}
          <input
            key={q}
            type="search"
            name="q"
            aria-label="대화 검색"
            defaultValue={q}
            placeholder="번호·최근 내용 검색"
            className="min-w-0 flex-1 rounded border border-line px-2 py-1 text-xs"
          />
          <button type="submit" className="rounded border border-line px-2 py-1 text-xs">검색</button>
        </form>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {threads.length === 0 ? (
          <EmptyState
            icon="inbox"
            title="대화 없음"
            description={
              q
                ? '검색 조건에 맞는 대화가 없습니다.'
                : filter === 'unread'
                  ? '읽지 않은 대화가 없습니다.'
                  : '주고받은 메시지가 아직 없습니다.'
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
                  href={buildHref(t.id, filter, q, page.offset)}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
      <nav aria-label="대화 목록 페이지" className="flex shrink-0 items-center justify-between border-t border-line px-4 py-2 text-xs">
        {page.offset > 0 ? (
          <Link href={buildHref(activeId, filter, q, Math.max(0, page.offset - page.limit))} className="rounded px-2 py-1 hover:bg-gray-1">이전</Link>
        ) : (
          <button type="button" disabled className="px-2 py-1 text-ink-dim">이전</button>
        )}
        <span className="text-ink-dim">
          {threads.length ? `${page.offset + 1}–${page.offset + threads.length}` : '0'} / {page.total}
        </span>
        {page.hasMore ? (
          <Link href={buildHref(activeId, filter, q, page.offset + page.limit)} className="rounded px-2 py-1 hover:bg-gray-1">다음</Link>
        ) : (
          <button type="button" disabled className="px-2 py-1 text-ink-dim">다음</button>
        )}
      </nav>
    </div>
  );
}
