import { PageHeader } from '@/components/shell';
import {
  ChatFilters,
  ThreadList,
  ThreadPreview,
  type ChatFilter,
} from '@/components/chat';
import { fetchThreads } from '@/lib/chat';

const VALID_FILTERS = new Set<ChatFilter>(['all', 'unread', 'urgent']);

function normalizeFilter(raw: string | string[] | undefined): ChatFilter {
  if (typeof raw === 'string' && VALID_FILTERS.has(raw as ChatFilter)) {
    return raw as ChatFilter;
  }
  return 'all';
}

type ChatPageProps = {
  searchParams?: {
    filter?: string;
    selected?: string;
  };
};

export default async function ChatPage({ searchParams }: ChatPageProps) {
  const filter = normalizeFilter(searchParams?.filter);
  const selected = searchParams?.selected;

  const threads = await fetchThreads({
    unread: filter === 'unread',
  });
  const unreadCount = threads.filter((t) => t.unread).length;
  const active = selected ? threads.find((t) => t.id === selected) : undefined;

  return (
    <div className="k-page">
      <PageHeader
        title="대화방"
        sub={`${threads.length}개 대화 · 미답 ${unreadCount}건`}
      />

      <div className="overflow-hidden rounded-lg border border-line bg-surface">
        <div
          className="grid min-h-[560px]"
          style={{
            gridTemplateColumns: '200px 360px 1fr',
          }}
        >
          <ChatFilters active={filter} unreadCount={unreadCount} />
          <ThreadList threads={threads} activeId={selected} filter={filter} />
          <ThreadPreview thread={active} />
        </div>
      </div>
    </div>
  );
}
