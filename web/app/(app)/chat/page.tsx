import { PageHeader } from '@/components/shell';
import {
  ChatFilters,
  ThreadList,
  ThreadView,
  type ChatFilter,
} from '@/components/chat';
import { EmptyState } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { fetchThread, fetchThreads } from '@/lib/chat';

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

  // 선택된 스레드가 있으면 본문까지 로드 — 클릭 즉시 채팅 UI 노출.
  // 예전엔 ThreadPreview(요약 카드) + "스레드 열기" 버튼을 거쳐 /chat/{id}
  // 로 이동해야 했는데, 대화방은 선택하자마자 메시지와 입력창이 보이는
  // 것이 자연스러운 UX. 이제 /chat?selected=... 에서 바로 ThreadView 렌더.
  let threadDetail = null;
  if (selected) {
    try {
      threadDetail = await fetchThread(selected);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 404)) throw err;
    }
  }

  return (
    <div className="k-page flex h-full flex-col">
      <PageHeader
        title="대화방"
        sub={`${threads.length}개 대화 · 미답 ${unreadCount}건`}
      />

      <div className="flex-1 min-h-0 overflow-hidden rounded-lg border border-line bg-surface">
        <div
          className="grid h-full"
          style={{ gridTemplateColumns: '200px 320px 1fr' }}
        >
          <ChatFilters active={filter} unreadCount={unreadCount} />
          <ThreadList threads={threads} activeId={selected} filter={filter} />
          {threadDetail ? (
            <div className="flex min-h-0 flex-col bg-surface-subtle p-3">
              <ThreadView thread={threadDetail} />
            </div>
          ) : (
            <div className="flex items-center justify-center bg-surface-subtle">
              <EmptyState
                icon="chat"
                title="대화 선택"
                description="왼쪽 목록에서 대화를 선택하면 바로 대화가 표시됩니다."
                size="md"
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
