import Link from 'next/link';
import type { Route } from 'next';
import { PageHeader } from '@/components/shell';
import {
  ChatFilters,
  ChatLiveRefresh,
  ThreadList,
  ThreadView,
  type ChatFilter,
} from '@/components/chat';
import { EmptyState } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { fetchThread, fetchThreadPage, getDeliveryRefreshIds } from '@/lib/chat';
import { formatPhone, threadDisplayName } from '@/lib/phone';

const VALID_FILTERS = new Set<ChatFilter>(['all', 'unread']);

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
    q?: string;
    offset?: string;
  };
};

export default async function ChatPage({ searchParams }: ChatPageProps) {
  const filter = normalizeFilter(searchParams?.filter);
  const selected = searchParams?.selected;
  const q = typeof searchParams?.q === 'string' ? searchParams.q.trim() : '';
  const rawOffset = Number(searchParams?.offset ?? 0);
  const offset = Number.isSafeInteger(rawOffset) && rawOffset >= 0 ? rawOffset : 0;

  const { data: threads, meta } = await fetchThreadPage({
    q, unread: filter === 'unread', limit: 200, offset,
  });
  const unreadCount = meta.unreadTotal;

  // 선택된 스레드가 있으면 본문까지 로드 — 클릭 즉시 채팅 UI 노출.
  // 예전엔 요약 카드 + "스레드 열기" 버튼을 거쳐 /chat/{id}
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
    // 뷰포트-앵커 height. `.k-page` 클래스의 `flex: 1 1 0%` 때문에 `flex-basis:
    // 0%` 가 `height: calc(...)` 를 덮어써서 앞선 수정이 먹히지 않았다 (flex
    // item 은 basis 가 0% 면 height 를 무시). `.k-page` 를 아예 빼고 padding/
    // min-width 를 Tailwind 로 직접 선언해 specificity 충돌을 원천 제거.
    // 56px = 상단 바(.k-topbar) 높이. 여백은 `.k-page` 와 같은 32px, 아래만 20px.
    // html 글자 크기가 14px 이라 rem 단위(px-8 등) 대신 px 로 적는다.
    <div className="flex h-[calc(100dvh_-_56px)] min-h-0 min-w-0 flex-col px-[32px] pb-[20px] pt-[32px]">
      {/* SSE 구독 — 고객 회신, 열린 대화의 전달 대기 메시지 결과를 새로고침 없이 갱신(UI 없음). */}
      <ChatLiveRefresh
        threadId={threadDetail?.id}
        deliveryRefreshIds={getDeliveryRefreshIds(threadDetail)}
      />
      <PageHeader
        title="대화방"
        sub={`${meta.total}개 대화 · 안읽음 ${unreadCount}건`}
      />

      <div className="flex-1 min-h-0 overflow-hidden rounded-lg border border-line bg-surface">
        {/* v2: 왼쪽 필터 칸을 없애고 필터를 목록 위로 올렸다 → 목록 | 대화 두 칸 */}
        <div className="grid h-full grid-cols-[340px_minmax(0,1fr)]">
          <div className="flex min-h-0 flex-col border-r border-line">
            <ChatFilters active={filter} unreadCount={unreadCount} selected={selected} q={q} />
            <ThreadList threads={threads} activeId={selected} filter={filter} q={q} page={meta} />
          </div>
          {threadDetail ? (
            <div className="flex min-h-0 flex-col bg-surface-subtle">
              <div className="flex shrink-0 items-center gap-3 border-b border-line bg-surface px-5 py-3">
                <div className="min-w-0">
                  <div className="truncate text-[15px] font-semibold leading-[22px] text-ink">
                    {threadDisplayName(threadDetail)}
                  </div>
                  <div className="text-xs tabular-nums text-ink-dim">
                    {formatPhone(threadDetail.phone)} · 메시지 {threadDetail.messages.length}개
                  </div>
                </div>
                <Link
                  href={`/chat/${encodeURIComponent(threadDetail.id)}` as Route}
                  className="k-link ml-auto shrink-0 text-md"
                >
                  연락처·통화 기록 보기
                </Link>
              </div>
              <div className="flex min-h-0 flex-1 flex-col p-3">
                <ThreadView thread={threadDetail} />
              </div>
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
